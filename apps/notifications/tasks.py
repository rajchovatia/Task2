import logging

import pybreaker
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from .models import Notification, NotificationDelivery
from .providers.email import (
    EmailProviderError,
    PermanentEmailError,
    send_via_sendgrid,
)
from .providers.push import PermanentPushError, PushProviderError, send_via_fcm

logger = logging.getLogger(__name__)

# ── Circuit Breakers ──
email_breaker = pybreaker.CircuitBreaker(
    fail_max=settings.CIRCUIT_BREAKER_FAIL_MAX,
    reset_timeout=settings.CIRCUIT_BREAKER_RESET_TIMEOUT,
    name="email_circuit_breaker",
)

push_breaker = pybreaker.CircuitBreaker(
    fail_max=settings.CIRCUIT_BREAKER_FAIL_MAX,
    reset_timeout=settings.CIRCUIT_BREAKER_RESET_TIMEOUT,
    name="push_circuit_breaker",
)


def _get_delivery(notification_id, channel):
    """Get delivery record, return None if already sent (idempotent)."""
    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification", "notification__type", "notification__recipient"
        ).get(notification_id=notification_id, channel=channel)

        if delivery.status == NotificationDelivery.Status.SENT:
            logger.info(
                "Delivery %s already sent, skipping (idempotent)", delivery.id
            )
            return None

        return delivery
    except NotificationDelivery.DoesNotExist:
        logger.error(
            "No %s delivery found for notification %s", channel, notification_id
        )
        return None


def _mark_sent(delivery, provider_id=""):
    """Mark delivery as sent and track analytics."""
    delivery.status = NotificationDelivery.Status.SENT
    delivery.provider_id = provider_id
    delivery.last_attempt_at = timezone.now()
    delivery.save(update_fields=["status", "provider_id", "last_attempt_at"])

    # Track delivery analytics
    _track_analytics(delivery, "delivered")


def _mark_failed(delivery, error_message):
    """Mark delivery as permanently failed and track analytics."""
    delivery.status = NotificationDelivery.Status.FAILED
    delivery.error_message = error_message
    delivery.last_attempt_at = timezone.now()
    delivery.save(update_fields=["status", "error_message", "last_attempt_at"])

    # Track failure analytics
    _track_analytics(delivery, "failed", {"error": error_message})


def _track_analytics(delivery, event_type, metadata=None):
    """Track delivery event in analytics."""
    try:
        from apps.analytics.services import AnalyticsService

        AnalyticsService.track_event(
            notification=delivery.notification,
            event_type=event_type,
            channel=delivery.channel,
            metadata=metadata,
        )
    except Exception as exc:
        logger.error("Failed to track analytics: %s", str(exc))


def _increment_attempts(delivery):
    """Increment delivery attempt count."""
    delivery.attempts += 1
    delivery.last_attempt_at = timezone.now()
    delivery.save(update_fields=["attempts", "last_attempt_at"])


# ── Email Task ──
@shared_task(
    bind=True,
    name="apps.notifications.tasks.send_email",
    max_retries=5,
    retry_backoff=True,
    retry_jitter=True,
    acks_late=True,
)
def send_email(self, notification_id):
    """Send email notification via SendGrid with circuit breaker and retry."""
    delivery = _get_delivery(notification_id, NotificationDelivery.Channel.EMAIL)
    if delivery is None:
        return

    try:
        provider_id = email_breaker.call(send_via_sendgrid, delivery.notification)
        _mark_sent(delivery, provider_id or "")
        logger.info("Email delivered for notification %s", notification_id)

    except pybreaker.CircuitBreakerError:
        logger.warning("Email circuit breaker OPEN, retrying in 60s")
        _increment_attempts(delivery)
        raise self.retry(countdown=60)

    except PermanentEmailError as exc:
        logger.error("Permanent email failure: %s", str(exc))
        _mark_failed(delivery, str(exc))

    except (EmailProviderError, Exception) as exc:
        logger.error("Email delivery error: %s", str(exc))
        _increment_attempts(delivery)
        raise self.retry(exc=exc)


# ── Push Task ──
@shared_task(
    bind=True,
    name="apps.notifications.tasks.send_push",
    max_retries=5,
    retry_backoff=True,
    retry_jitter=True,
    acks_late=True,
)
def send_push(self, notification_id):
    """Send push notification via FCM with circuit breaker and retry."""
    delivery = _get_delivery(notification_id, NotificationDelivery.Channel.PUSH)
    if delivery is None:
        return

    try:
        provider_id = push_breaker.call(send_via_fcm, delivery.notification)
        _mark_sent(delivery, provider_id or "")
        logger.info("Push delivered for notification %s", notification_id)

    except pybreaker.CircuitBreakerError:
        logger.warning("Push circuit breaker OPEN, retrying in 60s")
        _increment_attempts(delivery)
        raise self.retry(countdown=60)

    except PermanentPushError as exc:
        logger.error("Permanent push failure: %s", str(exc))
        _mark_failed(delivery, str(exc))

    except (PushProviderError, Exception) as exc:
        logger.error("Push delivery error: %s", str(exc))
        _increment_attempts(delivery)
        raise self.retry(exc=exc)


# ── In-App Task (WebSocket) ──
@shared_task(
    bind=True,
    name="apps.notifications.tasks.send_inapp",
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
    acks_late=True,
)
def send_inapp(self, notification_id):
    """Send in-app notification via WebSocket channel layer."""
    delivery = _get_delivery(notification_id, NotificationDelivery.Channel.INAPP)
    if delivery is None:
        return

    try:
        notification = delivery.notification
        channel_layer = get_channel_layer()

        if channel_layer is None:
            raise Exception("Channel layer not available")

        group_name = f"notifications_{notification.recipient_id}"
        data = {
            "type": "new_notification",
            "id": str(notification.id),
            "title": notification.title,
            "body": notification.body,
            "notification_type": (
                notification.type.name if notification.type else None
            ),
            "priority": (
                notification.type.priority if notification.type else 5
            ),
            "created_at": notification.created_at.isoformat(),
            "metadata": notification.metadata or {},
        }

        # Send notification to WebSocket group
        async_to_sync(channel_layer.group_send)(
            group_name,
            {"type": "notification.send", "data": data},
        )

        # Send updated unread count
        unread_count = Notification.objects.filter(
            recipient_id=notification.recipient_id, is_read=False
        ).count()
        async_to_sync(channel_layer.group_send)(
            group_name,
            {"type": "unread.count.update", "count": unread_count},
        )

        _mark_sent(delivery)
        logger.info("In-app delivered for notification %s", notification_id)

    except Exception as exc:
        logger.error("In-app delivery error: %s", str(exc))
        _increment_attempts(delivery)
        raise self.retry(exc=exc)
