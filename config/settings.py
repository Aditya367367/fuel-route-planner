import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
DEV_SECRET = "dev-only-insecure-key"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET)
if not DEBUG and SECRET_KEY == DEV_SECRET:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "stations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "stations.middleware.RateLimitMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# Route results and geocoding live in "default". Rate-limit counters get their own
# cache so a burst of large route payloads can't evict them. Both are per-process
# unless REDIS_URL is set, in which case every worker shares one count.
REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL},
        "ratelimit": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL},
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "routes",
            "OPTIONS": {"MAX_ENTRIES": 2000},
        },
        "ratelimit": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ratelimit",
            "OPTIONS": {"MAX_ENTRIES": 10000},
        },
    }

RATE_LIMIT = {
    "ENABLED": os.environ.get("RATE_LIMIT_ENABLED", "1") == "1",
    "REQUESTS": int(os.environ.get("RATE_LIMIT_REQUESTS", "60")),
    "WINDOW_SECONDS": int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
    "PATH_PREFIX": "/api/",
    # How many reverse proxies sit in front of Django. Leave at 0 unless you run behind
    # nginx or a load balancer, otherwise callers can fake their IP with X-Forwarded-For.
    "TRUSTED_PROXIES": int(os.environ.get("RATE_LIMIT_TRUSTED_PROXIES", "0")),
}

ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org"
ORS_TIMEOUT_SECONDS = 15

FUEL_PLANNER = {
    "MAX_RANGE_MILES": 500,
    "MPG": 10,
    "CORRIDOR_MILES": 5,  # stations further than this from the route are ignored
    "START_WITH_FULL_TANK": True,
    "ROUTE_CACHE_SECONDS": 60 * 60 * 24,
}

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"  # OSM tiles reject requests with no Referer
