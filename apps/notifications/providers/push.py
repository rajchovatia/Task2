import logging

from django.conf import settings
from firebase_admin.messaging import Message, Notification as FCMNotification

logger = logging.getLogger(__name__)


class PushProviderError(Exception):
    """Raised when push provider fails (transient — retry)."""
    pass


class PermanentPushError(Exception):
    """Raised when push permanently fails (invalid token — no retry)."""
    pass


def send_via_fcm(notification):
    try:
        from fcm_django.models import FCMDevice

        devices = FCMDevice.objects.filter(
            user=notification.recipient, active=True
        )

        if not devices.exists():
            raise PermanentPushError(
                f"No active devices for user {notification.recipient_id}"
            )

        # Build FCM message
        fcm_message = Message(
            notification=FCMNotification(
                title=notification.title,
                body=notification.body,
            ),
            data={
                "notification_id": str(notification.id),
                "notification_type": notification.type.name if notification.type else "",
                "priority": str(notification.type.priority) if notification.type else settings.DEFAULT_NOTIFICATION_PRIORITY,
            },
        )

        # Send to all user's devices
        response = devices.send_message(fcm_message)

        # Extract message ID from response safely
        provider_id = ""
        if (
            hasattr(response, "responses")
            and response.responses
            and len(response.responses) > 0
        ):
            first = response.responses[0]
            if hasattr(first, "message_id") and first.message_id:
                provider_id = first.message_id

        logger.info(
            "Push sent for notification %s to %d devices",
            notification.id,
            devices.count(),
        )
        return provider_id

    except (PermanentPushError, PushProviderError):
        raise
    except Exception as exc:
        logger.error(
            "Push provider error for notification %s: %s",
            notification.id,
            str(exc),
        )
        raise PushProviderError(str(exc)) from exc
