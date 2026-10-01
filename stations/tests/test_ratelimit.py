import unittest

from stations.ratelimit import FixedWindowLimiter, client_ip


class FakeCache:
    """Just enough of Django's cache API: add() and incr(), with expiry."""

    def __init__(self, clock):
        self.clock = clock
        self.data = {}

    def _live(self, key):
        item = self.data.get(key)
        if item and item[1] > self.clock():
            return item
        self.data.pop(key, None)
        return None

    def add(self, key, value, timeout):
        if self._live(key):
            return False
        self.data[key] = [value, self.clock() + timeout]
        return True

    def incr(self, key):
        item = self._live(key)
        if not item:
            raise ValueError(key)
        item[0] += 1
        return item[0]


class LimiterTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        clock = lambda: self.now
        self.limiter = FixedWindowLimiter(FakeCache(clock), limit=3, window=60, clock=clock)

    def test_allows_up_to_limit_then_blocks(self):
        results = [self.limiter.hit("1.1.1.1") for _ in range(5)]
        self.assertEqual([r.allowed for r in results], [True, True, True, False, False])
        self.assertEqual([r.remaining for r in results], [2, 1, 0, 0, 0])

    def test_ips_are_counted_separately(self):
        for _ in range(3):
            self.limiter.hit("1.1.1.1")
        self.assertFalse(self.limiter.hit("1.1.1.1").allowed)
        self.assertTrue(self.limiter.hit("2.2.2.2").allowed)

    def test_window_resets(self):
        for _ in range(4):
            self.limiter.hit("1.1.1.1")
        self.now += 60
        self.assertTrue(self.limiter.hit("1.1.1.1").allowed)

    def test_reset_in_counts_down_to_window_end(self):
        self.now = 1025.0  # window is 1020-1080, so 55s left
        self.assertEqual(self.limiter.hit("x").reset_in, 55)


class ClientIpTests(unittest.TestCase):
    def test_no_proxy_ignores_forwarded_header(self):
        meta = {"REMOTE_ADDR": "9.9.9.9", "HTTP_X_FORWARDED_FOR": "6.6.6.6"}
        self.assertEqual(client_ip(meta, 0), "9.9.9.9")

    def test_one_proxy_uses_last_entry(self):
        # a caller can prepend anything they like; only the proxy's own entry is real
        meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 7.7.7.7"}
        self.assertEqual(client_ip(meta, 1), "7.7.7.7")

    def test_two_proxies(self):
        meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 7.7.7.7, 10.0.0.9"}
        self.assertEqual(client_ip(meta, 2), "7.7.7.7")

    def test_header_missing_falls_back(self):
        self.assertEqual(client_ip({"REMOTE_ADDR": "9.9.9.9"}, 1), "9.9.9.9")

    def test_nothing_known(self):
        self.assertEqual(client_ip({}, 0), "unknown")


if __name__ == "__main__":
    unittest.main()
