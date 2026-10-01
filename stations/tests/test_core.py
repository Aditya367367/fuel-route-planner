import io
import unittest
import zipfile

import numpy as np

from stations.services.geo import build_profile, decode_polyline, match_stations
from stations.services.gazetteer import clean_place_name, load_gazetteer, normalize
from stations.services.optimizer import Candidate, InfeasibleRoute, plan_fuel_stops


def C(mile, price):
    return Candidate(mile=mile, price=price)


class OptimizerTests(unittest.TestCase):
    def test_short_trip_needs_no_fuel(self):
        self.assertEqual(plan_fuel_stops([C(100, 3)], 400), [])

    def test_multi_stop_cost(self):
        # start full(50g). reach 500 -> cheapest in reach is 450@3.0 (5g left).
        # fill to 50g (45g*3.0=135) -> 900@3.5 (5g left) -> buy 25g to finish: 87.5
        stops = plan_fuel_stops([C(400, 4.0), C(450, 3.0), C(900, 3.5)], 1200)
        self.assertAlmostEqual(sum(s.cost for s in stops), 222.5, places=6)
        self.assertEqual([s.candidate.mile for s in stops], [450, 900])

    def test_buys_only_enough_to_reach_cheaper_station(self):
        stops = plan_fuel_stops([C(300, 4.0), C(400, 3.0)], 800)
        # start 50g; go to 300@4 (20g left); cheaper at 400 -> buy 0 extra needed (10g to reach). 
        # at 400@3: 10g left; dest 400mi away, full reach 900 -> buy 30g
        self.assertEqual(len(stops), 1)
        self.assertAlmostEqual(stops[0].gallons, 30.0, places=6)
        self.assertAlmostEqual(stops[0].cost, 90.0, places=6)

    def test_never_exceeds_tank(self):
        stops = plan_fuel_stops([C(m, 3 + (m % 7) * 0.1) for m in range(50, 2000, 50)], 2000)
        tank, pos = 50.0, 0.0
        for s in stops:
            tank -= (s.candidate.mile - pos) / 10
            self.assertGreaterEqual(tank, -1e-6)
            tank += s.gallons
            self.assertLessEqual(tank, 50 + 1e-6)
            pos = s.candidate.mile
        self.assertGreaterEqual(tank - (2000 - pos) / 10, -1e-6)

    def test_empty_start_buys_at_origin(self):
        # nothing in the tank: buy 20g at the origin (4.0) to reach the 200mi station at 3.0
        stops = plan_fuel_stops([C(200, 3.0)], 600, start_gallons=0.0, origin_price=4.0)
        self.assertEqual([s.candidate.mile for s in stops], [0.0, 200])
        self.assertAlmostEqual(stops[0].gallons, 20.0, places=6)
        self.assertAlmostEqual(stops[1].gallons, 40.0, places=6)
        self.assertAlmostEqual(sum(s.cost for s in stops), 20 * 4.0 + 40 * 3.0, places=6)

    def test_empty_start_without_origin_price_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([C(200, 3.0)], 600, start_gallons=0.0)

    def test_infeasible_gap(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([C(100, 3)], 1200)


class GeoTests(unittest.TestCase):
    def test_polyline_known_vector(self):
        pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(pts, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_profile_and_matching(self):
        # straight line along lat 40 from lon -100 to -90
        coords = [(40.0, -100.0 + i * 0.1) for i in range(101)]
        prof = build_profile(coords)
        self.assertAlmostEqual(prof.total_miles, 10 * 69.17 * np.cos(np.radians(40)), delta=2)
        lat = np.array([40.05, 40.5, 45.0])   # near, ~34mi off, far
        lon = np.array([-95.0, -95.0, -95.0])
        idx, miles, detour = match_stations(prof, lat, lon, corridor_miles=10)
        self.assertEqual(list(idx), [0])
        self.assertAlmostEqual(miles[0], prof.total_miles / 2, delta=1)


class GazetteerTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(clean_place_name("Big Cabin town"), "big cabin")
        self.assertEqual(clean_place_name("Nashville-Davidson metropolitan government (balance)"), "nashville davidson")
        self.assertEqual(normalize("St. Louis"), "saint louis")
        self.assertEqual(normalize("Ft. Smith"), "fort smith")


    def test_consolidated_city_alias(self):
        header = "USPS\tGEOID\tANSICODE\tNAME\tLSAD\tFUNCSTAT\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG   \n"
        rows = [
            "TN\t1\t1\tNashville-Davidson metropolitan government (balance)\t00\tA\t8000\t0\t4\t0\t36.17\t-86.78   \n",
            "KY\t2\t2\tLexington-Fayette urban county\t00\tA\t6000\t0\t4\t0\t38.04\t-84.46   \n",
            "KY\t3\t3\tLexington city\t25\tA\t10\t0\t4\t0\t11.11\t-11.11   \n",
        ]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("places.txt", header + "".join(rows))
        places = load_gazetteer(zip_bytes=buf.getvalue())
        self.assertEqual(places[("TN", "nashville")], (36.17, -86.78))
        # an exact "Lexington" entry must win over the alias from "Lexington-Fayette"
        self.assertEqual(places[("KY", "lexington")], (11.11, -11.11))

if __name__ == "__main__":
    unittest.main()
