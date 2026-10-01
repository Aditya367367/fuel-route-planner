# Fuel route planner

Give it a start and a finish in the USA. It returns the driving route, the cheapest places to
fuel up along the way, and what the fuel costs in total. The car has a 500 mile range and does
10 mpg, so long trips get several stops.

Built on Django 6.1.1 (Python 3.12 or newer). Routing and geocoding come from
[OpenRouteService](https://openrouteservice.org/), which has a free tier.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ORS_API_KEY=your-key        # free key from openrouteservice.org
python manage.py migrate
python manage.py load_stations     # one-off: reads data/*.csv and adds coordinates
python manage.py test stations
python manage.py runserver
```

`load_stations` downloads the Census places file once. If that fails, download it yourself and run
`python manage.py load_stations --gazetteer path/to/2024_Gaz_place_national.zip`.

Restart the server after running `load_stations`, because stations are cached in memory at startup.

## Use it

```bash
curl "http://localhost:8000/api/route/?start=Chicago,IL&finish=Dallas,TX"

curl -X POST localhost:8000/api/route/ -H 'Content-Type: application/json' \
     -d '{"start": "41.88,-87.63", "finish": "32.78,-96.80"}'
```

`start` and `finish` can be place names or `lat,lon`. Open `/api/route/map/?start=...&finish=...`
in a browser for the map.

The response has `fuel_stops`, `total_fuel_cost`, `distance_miles`, a GeoJSON `route_geojson`, a
`map_url`, and `meta` showing how many external calls were made and how long it took.

| Status | Meaning |
|---|---|
| 400 | bad or missing input, or a place outside the USA |
| 422 | a stretch of road with no station inside the car's range |
| 429 | rate limit hit, see `Retry-After` |
| 502 | the routing service failed |
| 503 | station data hasn't been loaded |

## Rate limiting

Every `/api/` request counts against the caller's IP: 60 per minute by default. Over the limit you
get a 429 with a `Retry-After` header. Each response also carries `X-RateLimit-Limit`,
`X-RateLimit-Remaining` and `X-RateLimit-Reset`.

Change it with `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW` or `RATE_LIMIT_ENABLED=0`. The counters
are kept in memory per process; set `REDIS_URL` if you run more than one worker. If the app sits
behind a reverse proxy, set `RATE_LIMIT_TRUSTED_PROXIES` to the number of proxies, otherwise every
caller shares the proxy's IP.

## How it keeps API calls low

- Coordinates as input need one call (directions). A place name adds one geocoding call, cached for 30 days.
- The same trip asked twice is served from cache with no external call.
- Stations sit in numpy arrays in memory, so a request never queries the database.

## How the stops are chosen

For each station near the route I know its mile marker and price. At a station: if a cheaper one is
within a full tank, buy just enough to reach it. If not, and the finish is in range, buy just enough
to finish. Otherwise fill up and drive to the cheapest station in range. I checked this against a
brute-force solver on a few hundred random routes and the costs matched.

## Assumptions

- The CSV has no coordinates, so each station is placed at the centre of its city (Census gazetteer).
  Stations within 5 miles of the route (`CORRIDOR_MILES`) are considered. On the map the red marker
  is the spot on the route, the grey dot is the recorded location.
- The car starts with a full tank that isn't charged for. Set `START_WITH_FULL_TANK` to `False` in
  `config/settings.py` to charge for every gallon.
- Duplicate CSV rows are merged and the lowest price is kept. Cities missing from the gazetteer are
  skipped and listed when you run `load_stations`.
- Prices come from the CSV and are not live.

## Checking it

`python manage.py test stations` runs the unit tests. With the server running,
`python3 scripts/smoke_test.py` runs an end-to-end check against it (add `--ratelimit` to also test
the 429, and wait a minute afterwards).
