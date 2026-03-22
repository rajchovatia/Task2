import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ["SECRET_KEY"]  # No fallback — must be set in env
DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Application definition
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    "channels",
    "anymail",
    "fcm_django",
    # Monitoring & Observability
    "django_prometheus",
    "django_guid",
    # Local apps
    "apps.notifications",
    "apps.analytics",
    "apps.devices",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django_guid.middleware.guid_middleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Channels — Redis channel layer
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.getenv("REDIS_CHANNELS_URL", "redis://localhost:6380/0")],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# Database — PostgreSQL via PgBouncer
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "RNS"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    },
    "replica": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_REPLICA_DB", os.getenv("POSTGRES_DB", "RNS")),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_REPLICA_HOST", os.getenv("POSTGRES_HOST", "localhost")),
        "PORT": os.getenv("POSTGRES_REPLICA_PORT", os.getenv("POSTGRES_PORT", "5432")),
        "CONN_MAX_AGE": 0,
    },
}

# Database Router — read/write splitting
DATABASE_ROUTERS = ["apps.notifications.db_router.PrimaryReplicaRouter"]

# Cache — Redis
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_CACHE_URL", "redis://localhost:6381/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.notifications.pagination.NotificationCursorPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
}

# ── Celery ──
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672/")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6382/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 minutes soft limit
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Fair scheduling
CELERY_TASK_ACKS_LATE = True  # Acknowledge after task completes

# ── Anymail (Email — SendGrid primary, SES fallback) ──
ANYMAIL = {
    "SENDGRID_API_KEY": os.getenv("SENDGRID_API_KEY", ""),
    "AMAZON_SES_CLIENT_PARAMS": {
        "region_name": os.getenv("AWS_SES_REGION", "us-east-1"),
    },
}
EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "notifications@example.com")

# ── FCM (Push Notifications) ──
FCM_DJANGO_SETTINGS = {
    "ONE_DEVICE_PER_USER": False,
    "DELETE_INACTIVE_DEVICES": True,
    "APP_VERBOSE_NAME": "RNS Push Notifications",
    "FCM_SERVER_KEY": os.getenv("FCM_SERVER_KEY", ""),
}

# ══════════════════════════════════════════════════════════════
# Phase 6: Monitoring & Observability
# ══════════════════════════════════════════════════════════════

# ── django-guid (Correlation IDs) ──
DJANGO_GUID = {
    "GUID_HEADER_NAME": "X-Correlation-ID",
    "VALIDATE_GUID": False,
    "SKIP_CLEANUP": False,
    "RETURN_HEADER": True,
    "EXPOSE_HEADER": True,
    "INTEGRATIONS": [],
}

# ── Structured JSON Logging (python-json-logger) ──
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(correlation_id)s",
        },
        "verbose": {
            "format": "[{asctime}] {levelname} [{name}] {message}",
            "style": "{",
        },
    },
    "filters": {
        "correlation_id": {
            "()": "django_guid.log_filters.CorrelationId",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["correlation_id"],
        },
        "console_plain": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.notifications": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.analytics": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ── OpenTelemetry (Distributed Tracing) ──
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "False") == "True"
OTEL_JAEGER_HOST = os.getenv("OTEL_JAEGER_HOST", "jaeger")
OTEL_JAEGER_PORT = int(os.getenv("OTEL_JAEGER_PORT", "6831"))
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "rns-notification-system")

# ══════════════════════════════════════════════════════════════
# Notification System Configuration
# ══════════════════════════════════════════════════════════════

# Circuit breaker
CIRCUIT_BREAKER_FAIL_MAX = int(os.getenv("CIRCUIT_BREAKER_FAIL_MAX", "5"))
CIRCUIT_BREAKER_RESET_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "60"))

# Idempotency
IDEMPOTENCY_TTL = int(os.getenv("IDEMPOTENCY_TTL", "86400"))  # 24 hours

# DLQ processing
DLQ_MAX_ATTEMPTS = int(os.getenv("DLQ_MAX_ATTEMPTS", "10"))
DLQ_BATCH_SIZE = int(os.getenv("DLQ_BATCH_SIZE", "100"))

# Digest
DIGEST_MAX_NOTIFICATIONS = int(os.getenv("DIGEST_MAX_NOTIFICATIONS", "50"))

# Cleanup
CLEANUP_READ_AFTER_DAYS = int(os.getenv("CLEANUP_READ_AFTER_DAYS", "90"))
CLEANUP_FCM_AFTER_DAYS = int(os.getenv("CLEANUP_FCM_AFTER_DAYS", "30"))

# Bulk notifications
BULK_BATCH_SIZE = int(os.getenv("BULK_BATCH_SIZE", "1000"))

# Default notification priority
DEFAULT_NOTIFICATION_PRIORITY = os.getenv("DEFAULT_NOTIFICATION_PRIORITY", "5")
