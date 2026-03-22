import os

from .base import *  # noqa: F401, F403

DEBUG = True

# Allow all hosts in development
ALLOWED_HOSTS = ["*"]

# CORS — allow all in dev
CORS_ALLOW_ALL_ORIGINS = True

# Channels — use in-memory layer only for local dev without Docker/Redis
# In Docker, use the Redis channel layer from base.py (don't override)
if os.getenv("REDIS_CHANNELS_URL") is None:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

# Local development: direct DB connection (no PgBouncer)
# Override base.py defaults when running without Docker
if os.getenv("POSTGRES_HOST") in (None, "localhost", "127.0.0.1"):
    DATABASES["default"]["HOST"] = "localhost"
    DATABASES["default"]["PORT"] = "5432"
    # In local dev, replica points to same DB as primary
    DATABASES["replica"]["HOST"] = "localhost"
    DATABASES["replica"]["PORT"] = "5432"
    DATABASES["replica"]["NAME"] = DATABASES["default"]["NAME"]
