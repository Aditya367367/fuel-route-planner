import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

from .geo import decode_polyline

log = logging.getLogger(__name__)

LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# (min_lat, max_lat, min_lon, max_lon): lower 48, Alaska, Hawaii. Rough boxes, only used to
# reject coordinates that are obviously not in the US.
US_BOXES = [
    (24.0, 50.0, -125.5, -66.5),
    (51.0, 72.0, -170.0, -129.0),
    (18.5, 22.5, -161.0, -154.5),
]

GEOCODE_TTL = 60 * 60 * 24 * 30

# One session for the whole process so repeat calls reuse the TLS connection.
_http = requests.Session()


class RoutingError(Exception):
    """The routing service failed or is unavailable. The message is safe to show callers."""


class LocationError(ValueError):
    """The caller's input isn't a usable US location."""


def in_us(lat, lon):
    return any(a <= lat <= b and c <= lon <= d for a, b, c, d in US_BOXES)


class OpenRouteService:
    def __init__(self):
        if not settings.ORS_API_KEY:
            log.error("ORS_API_KEY is not set")
            raise RoutingError("Routing service is not configured.")
        self.calls = 0

    def _call(self, method, path, **kwargs):
        self.calls += 1
        try:
            resp = _http.request(
                method,
                settings.ORS_BASE_URL + path,
                headers={"Authorization": settings.ORS_API_KEY},
                timeout=settings.ORS_TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.RequestException as exc:
            log.warning("ORS request failed: %s", exc)
            raise RoutingError("Routing service is unreachable.") from exc

        if resp.status_code == 200:
            return resp.json()

        log.warning("ORS %s %s -> %s %s", method, path, resp.status_code, resp.text[:300])
        if resp.status_code == 404:
            raise LocationError("No drivable road found near one of those locations.")
        if resp.status_code == 429:
            raise RoutingError("Routing service is busy, try again shortly.")
        raise RoutingError("Routing service returned an error.")

    def resolve(self, text):
        """Turn 'lat,lon' or a place name into (lat, lon, label). Coordinates cost no API call."""
        text = (text or "").strip()
        if not text:
            raise LocationError("Location is empty.")

        m = LATLON_RE.match(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if not in_us(lat, lon):
                raise LocationError(f"{text!r} is outside the USA.")
            return lat, lon, text

        key = "geo:" + " ".join(text.lower().split())
        found = cache.get(key)
        if found:
            return found

        data = self._call(
            "GET", "/geocode/search", params={"text": text, "boundary.country": "US", "size": 1}
        )
        features = data.get("features") or []
        if not features:
            raise LocationError(f"Couldn't find {text!r} in the USA.")
        lon, lat = features[0]["geometry"]["coordinates"]
        found = (lat, lon, features[0]["properties"].get("label", text))
        cache.set(key, found, GEOCODE_TTL)
        return found

    def directions(self, start, finish):
        """One routing call. Returns ([(lat, lon), ...], duration in seconds)."""
        data = self._call(
            "POST",
            "/v2/directions/driving-car",
            json={
                "coordinates": [[start[1], start[0]], [finish[1], finish[0]]],
                "instructions": False,
            },
        )
        try:
            route = data["routes"][0]
            return decode_polyline(route["geometry"]), route["summary"]["duration"]
        except (KeyError, IndexError) as exc:
            log.error("Unexpected ORS directions payload: %.300s", data)
            raise RoutingError("Routing service returned an unexpected response.") from exc
