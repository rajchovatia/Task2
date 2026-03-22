import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Redis key prefix for idempotency
IDEMPOTENCY_PREFIX = "idemp:"


def check_idempotency_redis(idempotency_key):
    if not idempotency_key:
        return True  # No key = no dedup

    redis_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}"
    is_new = cache.add(redis_key, "1", timeout=settings.IDEMPOTENCY_TTL)

    if not is_new:
        logger.info("Idempotency hit (Redis): key=%s", idempotency_key)

    return is_new


def clear_idempotency_redis(idempotency_key):
    if idempotency_key:
        redis_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}"
        cache.delete(redis_key)
