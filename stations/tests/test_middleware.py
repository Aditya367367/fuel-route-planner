from django.core.cache import caches
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from stations.middleware import RateLimitMiddleware

LIMITS = {
    "ENABLED": True,
    "REQUESTS": 3,
    "WINDOW_SECONDS": 60,
    "PATH_PREFIX": "/api/",
    "TRUSTED_PROXIES": 0,
}


@override_settings(RATE_LIMIT=LIMITS)
class RateLimitMiddlewareTests(SimpleTestCase):
    def setUp(self):
        caches["ratelimit"].clear()
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))

    def get(self, path="/api/route/", ip="1.2.3.4"):
        return self.middleware(self.factory.get(path, REMOTE_ADDR=ip))

    def test_blocks_after_limit(self):
        codes = [self.get().status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])

    def test_headers_on_success_and_on_block(self):
        first = self.get()
        self.assertEqual(first["X-RateLimit-Limit"], "3")
        self.assertEqual(first["X-RateLimit-Remaining"], "2")
        for _ in range(3):
            blocked = self.get()
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked)

    def test_other_ip_not_affected(self):
        for _ in range(4):
            self.get(ip="1.2.3.4")
        self.assertEqual(self.get(ip="5.6.7.8").status_code, 200)

    def test_paths_outside_api_are_ignored(self):
        for _ in range(10):
            self.assertEqual(self.get("/health/").status_code, 200)

    @override_settings(RATE_LIMIT={**LIMITS, "ENABLED": False})
    def test_can_be_switched_off(self):
        middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))
        for _ in range(10):
            self.assertEqual(middleware(self.factory.get("/api/route/")).status_code, 200)
