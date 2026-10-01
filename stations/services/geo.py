import math
from dataclasses import dataclass

import numpy as np

MILES_PER_DEG_LAT = 69.0
MILES_PER_DEG_LON_EQUATOR = 69.172
EARTH_RADIUS_MILES = 3958.8


def decode_polyline(encoded, precision=5):
    """Encoded polyline string -> [(lat, lon), ...]."""
    coords, index, lat, lng = [], 0, 0, 0
    factor = 10 ** precision
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lat / factor, lng / factor))
    return coords


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


@dataclass
class RouteProfile:
    lats: np.ndarray
    lons: np.ndarray
    miles: np.ndarray  # cumulative distance along the route, starting at 0

    @property
    def total_miles(self) -> float:
        return float(self.miles[-1])


def build_profile(coords, step_miles=0.5):
    """Distance-along-route profile, thinned to roughly one point per step_miles.

    A cross-country geometry has 10k+ points; thinning keeps matching fast and costs
    well under half a step in accuracy.
    """
    arr = np.asarray(coords, dtype=float)
    lat, lon = arr[:, 0], arr[:, 1]
    seg = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    targets = np.arange(0.0, cum[-1], step_miles)
    idx = np.unique(np.concatenate([np.searchsorted(cum, targets), [len(cum) - 1]]))
    idx = np.clip(idx, 0, len(cum) - 1)
    return RouteProfile(lat[idx], lon[idx], cum[idx])


def match_stations(profile, st_lat, st_lon, corridor_miles, max_cells=1_000_000):
    """Stations within corridor_miles of the route.

    Returns (station indexes, mile marker of the nearest route point, distance off route).
    max_cells caps the size of the stations x route-points matrix built per chunk.
    """
    mean_lat = float(profile.lats.mean())
    pad_lat = corridor_miles / MILES_PER_DEG_LAT
    pad_lon = corridor_miles / (MILES_PER_DEG_LON_EQUATOR * max(math.cos(math.radians(mean_lat)), 0.2))
    box = (
        (st_lat >= profile.lats.min() - pad_lat)
        & (st_lat <= profile.lats.max() + pad_lat)
        & (st_lon >= profile.lons.min() - pad_lon)
        & (st_lon <= profile.lons.max() + pad_lon)
    )
    cand = np.flatnonzero(box)
    if cand.size == 0:
        e = np.array([], dtype=float)
        return np.array([], dtype=int), e, e

    n = len(profile.lats)
    chunk = max(1, max_cells // n)
    out_idx, out_mile, out_detour = [], [], []
    for start in range(0, cand.size, chunk):
        ids = cand[start : start + chunk]
        slat = st_lat[ids][:, None]
        slon = st_lon[ids][:, None]
        dlat = (profile.lats[None, :] - slat) * MILES_PER_DEG_LAT
        coslat = np.cos(np.radians((profile.lats[None, :] + slat) / 2))
        dlon = (profile.lons[None, :] - slon) * MILES_PER_DEG_LON_EQUATOR * coslat
        d2 = dlat * dlat + dlon * dlon
        nearest = d2.argmin(axis=1)
        dist = np.sqrt(d2[np.arange(len(ids)), nearest])
        keep = dist <= corridor_miles
        out_idx.append(ids[keep])
        out_mile.append(profile.miles[nearest[keep]])
        out_detour.append(dist[keep])
    return np.concatenate(out_idx), np.concatenate(out_mile), np.concatenate(out_detour)
