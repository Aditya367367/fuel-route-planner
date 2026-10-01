import hashlib
import time

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .geo import build_profile, haversine_miles, match_stations
from .optimizer import Candidate, plan_fuel_stops
from .routing import LocationError, OpenRouteService
from .store import get_store


class StationDataError(Exception):
    """No stations in the database, so there is nothing to plan with."""


def cache_key(start, finish):
    norm = lambda s: " ".join(s.lower().replace(",", " , ").split()).replace(" , ", ",")
    return "plan:" + hashlib.sha1(f"{norm(start)}|{norm(finish)}".encode()).hexdigest()


def plan_route(start, finish):
    cfg = settings.FUEL_PLANNER
    key = cache_key(start, finish)
    hit = cache.get(key)
    if hit:
        return {**hit, "meta": {**hit["meta"], "cached": True, "external_api_calls": 0, "elapsed_ms": 0}}

    store = get_store()
    if len(store.lat) == 0:
        raise StationDataError("No station data loaded. Run `python manage.py load_stations`.")

    t0 = time.perf_counter()
    ors = OpenRouteService()
    s_lat, s_lon, s_label = ors.resolve(start)
    f_lat, f_lon, f_label = ors.resolve(finish)
    if haversine_miles(s_lat, s_lon, f_lat, f_lon) < 0.5:
        raise LocationError("Start and finish are the same place.")
    coords, duration = ors.directions((s_lat, s_lon), (f_lat, f_lon))

    profile = build_profile(coords)
    idx, miles, off = match_stations(profile, store.lat, store.lon, cfg["CORRIDOR_MILES"])
    candidates = [
        Candidate(float(m), float(store.price[i]), ref=(int(i), float(d)))
        for i, m, d in zip(idx, miles, off)
    ]

    # Starting empty means buying at the origin. There's no station there, so price it
    # like the nearest listed one.
    start_empty = not cfg["START_WITH_FULL_TANK"]
    origin_price = min(candidates, key=lambda c: c.mile).price if start_empty and candidates else None
    stops = plan_fuel_stops(
        candidates,
        profile.total_miles,
        max_range=cfg["MAX_RANGE_MILES"],
        mpg=cfg["MPG"],
        start_gallons=0.0 if start_empty else None,
        origin_price=origin_price,
    )

    fuel_stops = [stop_payload(n, s, store, profile, s_label) for n, s in enumerate(stops, 1)]

    # Every second profile point is plenty for drawing the line (~1 mile apart).
    line = [[round(float(lo), 5), round(float(la), 5)] for la, lo in zip(profile.lats[::2], profile.lons[::2])]
    line.append([round(float(profile.lons[-1]), 5), round(float(profile.lats[-1]), 5)])

    features = [{"type": "Feature", "properties": {"kind": "route"},
                 "geometry": {"type": "LineString", "coordinates": line}}]
    for f in fuel_stops:
        features.append({
            "type": "Feature",
            "properties": {"kind": "fuel_stop", "stop": f["stop"], "name": f["name"],
                           "price_per_gallon": f["price_per_gallon"], "cost": f["cost"]},
            "geometry": {"type": "Point", "coordinates": [f["longitude"], f["latitude"]]},
        })

    result = {
        "start": {"query": start, "label": s_label, "latitude": s_lat, "longitude": s_lon},
        "finish": {"query": finish, "label": f_label, "latitude": f_lat, "longitude": f_lon},
        "distance_miles": round(profile.total_miles, 1),
        "duration_hours": round(duration / 3600, 2),
        "assumptions": {
            "max_range_miles": cfg["MAX_RANGE_MILES"],
            "mpg": cfg["MPG"],
            "starts_with_full_tank_unbilled": cfg["START_WITH_FULL_TANK"],
            "station_search_corridor_miles": cfg["CORRIDOR_MILES"],
        },
        "fuel_stops": fuel_stops,
        "total_gallons_purchased": round(sum(s.gallons for s in stops), 2),
        "total_fuel_cost": round(sum(s.cost for s in stops), 2),
        "route_geojson": {"type": "FeatureCollection", "features": features},
        "meta": {
            "cached": False,
            "external_api_calls": ors.calls,
            "stations_in_corridor": len(candidates),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000),
        },
    }
    cache.set(key, result, cfg["ROUTE_CACHE_SECONDS"])
    return result


def stop_payload(number, stop, store, profile, start_label):
    mile = stop.candidate.mile
    # Station coordinates are city-level, so the marker is drawn on the route at the
    # station's mile instead of out in the town.
    on_route = (
        round(float(np.interp(mile, profile.miles, profile.lats)), 5),
        round(float(np.interp(mile, profile.miles, profile.lons)), 5),
    )
    if stop.candidate.ref is None:  # the origin purchase when the trip starts empty
        info = {"name": "Start of trip", "address": "", "city": start_label, "state": "",
                "station_latitude": on_route[0], "station_longitude": on_route[1]}
        off_route = 0.0
    else:
        i, off_route = stop.candidate.ref
        row = store.rows[i]
        info = {"name": row["name"], "address": row["address"], "city": row["city"],
                "state": row["state"], "station_latitude": row["latitude"],
                "station_longitude": row["longitude"]}
    return {
        "stop": number,
        **info,
        "latitude": on_route[0],
        "longitude": on_route[1],
        "route_mile": round(mile, 1),
        "off_route_miles": round(off_route, 1),
        "price_per_gallon": round(stop.candidate.price, 3),
        "gallons_purchased": round(stop.gallons, 2),
        "cost": round(stop.cost, 2),
    }
