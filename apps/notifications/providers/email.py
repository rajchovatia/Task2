import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    """Raised when email provider fails (transient — retry)."""
    pass


class PermanentEmailError(Exception):
    """Raised when email permanently fails (bad address, unsubscribed — no retry)."""
    pass


class AllProvidersDownError(EmailProviderError):
    """Raised when all email providers fail."""
    pass


def send_via_sendgrid(notification):

    recipient_email = notification.recipient.email
    if not recipient_email:
        raise PermanentEmailError(f"User {notification.recipient_id} has no email")

    providers = [
        ("sendgrid", "anymail.backends.sendgrid.EmailBackend"),
        ("ses", "anymail.backends.amazon_ses.EmailBackend"),
    ]

    last_error = None
    for provider_name, backend_path in providers:
        try:
            provider_id = _send_with_backend(
                notification, recipient_email, backend_path
            )
            logger.info(
                "Email sent via %s for notification %s to %s",
                provider_name, notification.id, recipient_email,
            )
            return provider_id

        except PermanentEmailError:
            raise  # Don't failover on permanent errors

        except Exception as exc:
            logger.warning(
                "%s unavailable for notification %s: %s, trying next",
                provider_name, notification.id, str(exc),
            )
            last_error = exc
            continue

    raise AllProvidersDownError(
        f"All email providers failed: {str(last_error)}"
    )


def _send_with_backend(notification, recipient_email, backend_path):
    try:
        connection = get_connection(backend=backend_path)

        email = EmailMessage(
            subject=notification.title,
            body=notification.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
            connection=connection,
        )

        if notification.metadata:
            email.extra_headers = {
                "X-Notification-ID": str(notification.id),
                "X-Notification-Type": notification.type.name if notification.type else "",
            }

        result = email.send(fail_silently=False)

        if result == 0:
            raise EmailProviderError("Provider returned 0 sent count")

        provider_id = ""
        if hasattr(email, "anymail_status"):
            anymail_status = email.anymail_status
            if anymail_status.message_id:
                provider_id = anymail_status.message_id

        return provider_id

    except PermanentEmailError:
        raise
    except EmailProviderError:
        raise
    except Exception as exc:
        raise EmailProviderError(str(exc)) from exc
