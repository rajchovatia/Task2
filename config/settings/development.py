import os

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

CORS_ALLOW_ALL_ORIGINS = True

if os.getenv("REDIS_CHANNELS_URL") is None:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

if os.getenv("POSTGRES_HOST") in (None, "localhost", "127.0.0.1"):
    DATABASES["default"]["HOST"] = "localhost"
    DATABASES["default"]["PORT"] = "5432"
    DATABASES["replica"]["HOST"] = "localhost"
    DATABASES["replica"]["PORT"] = "5432"
    DATABASES["replica"]["NAME"] = DATABASES["default"]["NAME"]
