import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Redis key prefix for idempotency
IDEMPOTENCY_PREFIX = "idemp:"


def check_idempotency_redis(idempotency_key):
    """
    Layer 2: Redis SET NX — fast duplicate check before hitting DB.

    Returns:
        True if key is NEW (proceed with creation)
        False if key already EXISTS (duplicate — return existing)
    """
    if not idempotency_key:
        return True  # No key = no dedup

    redis_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}"
    # SET NX: returns True if key was set (new), False if already exists
    is_new = cache.add(redis_key, "1", timeout=settings.IDEMPOTENCY_TTL)

    if not is_new:
        logger.info("Idempotency hit (Redis): key=%s", idempotency_key)

    return is_new


def clear_idempotency_redis(idempotency_key):
    """Remove idempotency key from Redis (e.g., on creation failure rollback)."""
    if idempotency_key:
        redis_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}"
        cache.delete(redis_key)
