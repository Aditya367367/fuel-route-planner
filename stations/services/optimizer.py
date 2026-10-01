from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

EPS = 1e-9


class InfeasibleRoute(Exception):
    """A stretch of the route is longer than the car can cover between stations."""


@dataclass
class Candidate:
    mile: float
    price: float  # USD per gallon
    ref: Any = None


@dataclass
class Stop:
    candidate: Candidate
    gallons: float

    @property
    def cost(self):
        return self.gallons * self.candidate.price


def plan_fuel_stops(candidates, total_miles, max_range=500.0, mpg=10.0,
                    start_gallons=None, origin_price=None):
    """Cheapest way to drive total_miles, buying fuel only at the given candidates.

    The car starts with start_gallons (a full tank by default, not billed). If origin_price
    is set, fuel can also be bought at mile 0 at that price, which is how an empty start works.

    At each stop: if a cheaper station is within a full tank, buy just enough to reach the
    nearest one. Otherwise, if the finish is in range, buy just enough to get there. Otherwise
    fill up and head for the cheapest station in range.
    """
    capacity = max_range / mpg
    tank = capacity if start_gallons is None else min(start_gallons, capacity)

    cands = sorted((c for c in candidates if 0 < c.mile < total_miles), key=lambda c: c.mile)
    miles = [c.mile for c in cands]

    def between(lo, hi):
        return cands[bisect_right(miles, lo + EPS):bisect_right(miles, hi + EPS)]

    def cheapest(options):
        return min(options, key=lambda c: (c.price, -c.mile))

    pos = 0.0
    here = Candidate(0.0, origin_price) if origin_price is not None else None
    stops = []

    while True:
        if here is None:
            # Nothing to buy at the origin, so the starting tank has to reach a station.
            reach = pos + tank * mpg
            if reach >= total_miles - EPS:
                return stops
            options = between(pos, reach)
            if not options:
                raise InfeasibleRoute(f"No station within {tank * mpg:.0f} miles of the start.")
            nxt = cheapest(options)
            buy = 0.0
        else:
            full = pos + capacity * mpg
            options = between(pos, full)
            nxt = next((c for c in options if c.price < here.price), None)
            if nxt is not None:
                buy = max(0.0, (nxt.mile - pos) / mpg - tank)
            elif total_miles <= full + EPS:
                buy = max(0.0, (total_miles - pos) / mpg - tank)
                if buy > EPS:
                    stops.append(Stop(here, buy))
                return stops
            else:
                if not options:
                    raise InfeasibleRoute(f"No station within {max_range:.0f} miles after mile {pos:.0f}.")
                nxt = cheapest(options)
                buy = capacity - tank
            if buy > EPS:
                stops.append(Stop(here, buy))

        tank += buy - (nxt.mile - pos) / mpg
        pos, here = nxt.mile, nxt
