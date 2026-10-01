import time
from dataclasses import dataclass


@dataclass
class Result:
    allowed: bool
    limit: int
    remaining: int
    reset_in: int  # seconds until the current window ends


class FixedWindowLimiter:
    """Counts hits per key in fixed time windows, using any cache with add() and incr()."""

    def __init__(self, cache, limit, window, prefix="rl", clock=time.time):
        self.cache = cache
        self.limit = limit
        self.window = window
        self.prefix = prefix
        self.clock = clock

    def hit(self, ident):
        now = self.clock()
        slot = int(now // self.window)
        key = f"{self.prefix}:{ident}:{slot}"
        count = self._bump(key)
        reset_in = max(1, int(self.window - (now % self.window)))
        return Result(count <= self.limit, self.limit, max(0, self.limit - count), reset_in)

    def _bump(self, key):
        # add() only succeeds for the first hit in a window. If the key expires between
        # add() and incr() the incr raises ValueError, so go round again.
        for _ in range(3):
            if self.cache.add(key, 1, self.window + 5):
                return 1
            try:
                return self.cache.incr(key)
            except ValueError:
                continue
        return 1


def client_ip(meta, trusted_proxies=0):
    """Work out the caller's IP.

    With no proxy in front of the app, REMOTE_ADDR is the only thing we can trust.
    Behind N proxies that each append to X-Forwarded-For, the real client is the
    Nth entry from the right; anything further left can be forged by the caller.
    """
    remote = meta.get("REMOTE_ADDR", "") or "unknown"
    if trusted_proxies <= 0:
        return remote
    hops = [h.strip() for h in meta.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
    if len(hops) >= trusted_proxies:
        return hops[-trusted_proxies]
    return remote
