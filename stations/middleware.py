from django.conf import settings
from django.core.cache import caches
from django.http import JsonResponse

from .ratelimit import FixedWindowLimiter, client_ip


class RateLimitMiddleware:
    """Per-IP request cap for everything under /api/."""

    def __init__(self, get_response):
        self.get_response = get_response
        cfg = settings.RATE_LIMIT
        self.enabled = cfg["ENABLED"]
        self.prefix = cfg["PATH_PREFIX"]
        self.proxies = cfg["TRUSTED_PROXIES"]
        self.limiter = FixedWindowLimiter(caches["ratelimit"], cfg["REQUESTS"], cfg["WINDOW_SECONDS"])

    def __call__(self, request):
        if not self.enabled or not request.path.startswith(self.prefix):
            return self.get_response(request)

        result = self.limiter.hit(client_ip(request.META, self.proxies))
        if not result.allowed:
            response = JsonResponse(
                {"error": "Too many requests.", "retry_after": result.reset_in}, status=429
            )
            response["Retry-After"] = str(result.reset_in)
        else:
            response = self.get_response(request)

        response["X-RateLimit-Limit"] = str(result.limit)
        response["X-RateLimit-Remaining"] = str(result.remaining)
        response["X-RateLimit-Reset"] = str(result.reset_in)
        return response
