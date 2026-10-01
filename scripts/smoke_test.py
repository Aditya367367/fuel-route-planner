#!/usr/bin/env python3
"""Smoke test for the running API.

Start the server first (python manage.py runserver), then from the project root:
    python3 scripts/smoke_test.py [--base URL] [--skip-unit] [--ratelimit]

--ratelimit hammers the API until it gets a 429, so run it last and wait a minute afterwards.
Fresh requests use a tiny random coordinate offset so the cache never answers them.
"""
import argparse
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8000")
ap.add_argument("--skip-unit", action="store_true")
ap.add_argument("--ratelimit", action="store_true")
args = ap.parse_args()
BASE = args.base.rstrip("/")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def call(path, params=None, method="GET", body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, raw, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
    ms = (time.perf_counter() - t) * 1000
    try:
        js = json.loads(raw)
    except ValueError:
        js = None
    return status, js, raw.decode(errors="replace"), ctype, ms


def jitter():
    return f"{random.uniform(0, 0.0099):.4f}"[1:]  # e.g. ".0042" -> makes a new cache key


if not args.skip_unit:
    print("\n0. Unit tests (python manage.py test stations)")
    r = subprocess.run([sys.executable, "manage.py", "test", "stations"], capture_output=True, text=True)
    check("unit tests pass", r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1])

print("\n1. Input validation")
s, js, *_ = call("/api/route/", {"start": "41.88,-87.63"})
check("missing 'finish' -> 400", s == 400, f"got {s}")
s, js, *_ = call("/api/route/", {"start": "0,0", "finish": "32.77,-96.79"})
check("coordinates outside USA (0,0) -> 400", s == 400, f"got {s}")
s, js, *_ = call("/api/route/", {"start": "51.50,-0.12", "finish": "32.77,-96.79"})
check("London coordinates -> 400", s == 400, f"got {s}")
s, *_ = call("/api/route/", method="DELETE")
check("DELETE not allowed -> 405", s == 405, f"got {s}")
s, js, *_ = call("/api/route/", method="POST", body=None)
check("empty POST -> 400", s == 400, f"got {s}")

print("\n2. Short trip (< 500 miles)")
a = f"41.88{jitter()[1:]},-87.63"          # near Chicago
b = "39.77,-86.16"                          # Indianapolis
s, js, raw, ctype, ms = call("/api/route/", {"start": a, "finish": b})
check("status 200", s == 200, f"got {s}")
if s == 200:
    check("distance under 500 mi", js["distance_miles"] < 500, f"{js['distance_miles']} mi")
    if js["assumptions"]["starts_with_full_tank_unbilled"]:
        check("no fuel stops needed", js["fuel_stops"] == [] and js["total_fuel_cost"] == 0,
              f"{len(js['fuel_stops'])} stops, ${js['total_fuel_cost']}")

print("\n3. Long trip: Chicago -> Dallas (coordinates, fresh)")
a = f"41.87{random.randint(10, 99)},-87.6298"
b = "32.7767,-96.7970"
s, js, raw, ctype, ms = call("/api/route/", {"start": a, "finish": b})
check("status 200", s == 200, f"got {s}")
long_ok = s == 200
if long_ok:
    cfg = js["assumptions"]
    stops, dist = js["fuel_stops"], js["distance_miles"]
    mpg, rng = cfg["mpg"], cfg["max_range_miles"]
    check("distance plausible (900-1100 mi)", 900 < dist < 1100, f"{dist} mi")
    check("at least one fuel stop", len(stops) >= 1, f"{len(stops)} stops")

    miles = [0.0] + [x["route_mile"] for x in stops] + [dist]
    legs = [round(y - x, 1) for x, y in zip(miles, miles[1:])]
    check(f"no leg exceeds {rng} miles", all(l <= rng + 0.5 for l in legs), f"legs {legs}")
    check("stops are in order along the route", miles == sorted(miles))

    check("total cost = sum of stop costs", abs(js["total_fuel_cost"] - sum(x["cost"] for x in stops)) < 0.05)
    check("each cost = gallons x price", all(abs(x["gallons_purchased"] * x["price_per_gallon"] - x["cost"]) < 0.06 for x in stops))
    free = rng / mpg if cfg["starts_with_full_tank_unbilled"] else 0
    check("fuel conservation (bought + starting tank = miles / mpg)",
          abs(js["total_gallons_purchased"] + free - dist / mpg) < 0.15,
          f"{js['total_gallons_purchased']} + {free} vs {dist / mpg:.2f}")
    check("no tank overfill (each purchase <= capacity)", all(x["gallons_purchased"] <= rng / mpg + 0.01 for x in stops))
    check("stops within corridor", all(x["off_route_miles"] <= cfg["station_search_corridor_miles"] for x in stops),
          f"max {max([x['off_route_miles'] for x in stops] or [0])} mi")
    check("required fields present", all(k in stops[0] for k in
          ["name", "address", "city", "state", "latitude", "longitude", "price_per_gallon", "gallons_purchased", "cost"]))

    feats = js["route_geojson"]["features"]
    kinds = [f["properties"]["kind"] for f in feats]
    check("GeoJSON has route line + one point per stop", kinds.count("route") == 1 and kinds.count("fuel_stop") == len(stops))
    check("response has map_url", "map_url" in js)
    check("first request external calls == 1 (coordinates)", js["meta"]["external_api_calls"] == 1, js["meta"]["external_api_calls"])
    check("fresh response time < 5 s", ms < 5000, f"{ms:.0f} ms (server {js['meta']['elapsed_ms']} ms)")
    print(f"      route={dist} mi  stops={len(stops)}  cost=${js['total_fuel_cost']}  fresh={ms:.0f} ms")

print("\n4. Caching and POST")
if long_ok:
    s2, js2, _, _, ms2 = call("/api/route/", {"start": a, "finish": b})
    check("repeat is cached, 0 external calls", s2 == 200 and js2["meta"]["cached"] and js2["meta"]["external_api_calls"] == 0)
    check("repeat is fast (< 100 ms)", ms2 < 100, f"{ms2:.0f} ms")
    check("repeat gives same total", js2["total_fuel_cost"] == js["total_fuel_cost"])
    s3, js3, *_ = call("/api/route/", method="POST", body={"start": a, "finish": b})
    check("POST JSON works and matches GET", s3 == 200 and js3["total_fuel_cost"] == js["total_fuel_cost"], f"got {s3}")

print("\n5. Free-text places and map page")
s, js, raw, ctype, ms = call("/api/route/", {"start": "Denver, CO", "finish": "Kansas City, MO"})
check("free-text places work", s == 200, f"got {s}: {raw[:120] if s != 200 else ''}")
if s == 200:
    check("free-text uses <= 3 external calls", js["meta"]["external_api_calls"] <= 3, js["meta"]["external_api_calls"])
s, js, raw, ctype, ms = call("/api/route/map/", {"start": a, "finish": b})
check("map page returns HTML", s == 200 and "text/html" in ctype, f"got {s} {ctype}")
check("map page loads Leaflet and has data", "leaflet" in raw.lower() and 'id="plan"' in raw)
check("map page sets a Referer policy", 'name="referrer"' in raw)

if args.ratelimit:
    print("\n6. Rate limiting")

    def ping():
        try:
            with urllib.request.urlopen(BASE + "/api/route/", timeout=10) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers

    _, headers = ping()
    limit = int(headers.get("X-RateLimit-Limit", 0))
    check("responses carry X-RateLimit headers", limit > 0, f"limit {limit}")
    codes = [ping()[0] for _ in range(limit + 5)]
    check("requests over the limit get 429", 429 in codes)
    status, headers = ping()
    check("429 includes Retry-After", status == 429 and bool(headers.get("Retry-After")))
    print(f"      wait {headers.get('Retry-After', '?')}s before using the API again")

print(f"\n{'=' * 40}\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)