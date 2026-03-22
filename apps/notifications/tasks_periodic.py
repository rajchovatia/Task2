import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db.models import Count
from django.utils import timezone

from .models import Notification, NotificationDelivery, NotificationPreference

logger = logging.getLogger(__name__)

User = get_user_model()


@shared_task(name="apps.notifications.tasks_periodic.process_dlq")
def process_dlq():
    """
    Re-process failed deliveries from dead letter queues.
    Runs every 5 minutes via Celery Beat.
    """
    from django.db import transaction

    from .tasks import send_email, send_inapp, send_push

    task_map = {
        "email": send_email,
        "push": send_push,
        "inapp": send_inapp,
    }

    requeued = 0
    # Use select_for_update(skip_locked=True) to prevent race condition
    # when multiple DLQ processors run concurrently
    with transaction.atomic():
        failed_deliveries = list(
            NotificationDelivery.objects.select_for_update(skip_locked=True)
            .filter(
                status=NotificationDelivery.Status.FAILED,
                attempts__lt=django_settings.DLQ_MAX_ATTEMPTS,
            )
            .select_related("notification")[:django_settings.DLQ_BATCH_SIZE]
        )

        for delivery in failed_deliveries:
            task = task_map.get(delivery.channel)
            if task:
                # Reset status to pending before re-enqueuing
                delivery.status = NotificationDelivery.Status.PENDING
                delivery.save(update_fields=["status"])
                task.delay(str(delivery.notification_id))
                requeued += 1

    if requeued:
        logger.info("DLQ processor: re-queued %d failed deliveries", requeued)

    return {"requeued": requeued}


@shared_task(name="apps.notifications.tasks_periodic.send_digests")
def send_digests():
    """
    Send daily digest emails for users with digest_mode='daily'.
    Runs daily at 8 AM via Celery Beat.
    """
    yesterday = timezone.now() - timedelta(days=1)

    # Find users with daily digest preference
    digest_users = NotificationPreference.objects.filter(
        digest_mode=NotificationPreference.DigestMode.DAILY,
        email_enabled=True,
    ).select_related("user")

    sent = 0
    for pref in digest_users:
        user = pref.user
        if not user.email:
            continue

        # Get unread notifications from the last 24h
        notifications = Notification.objects.filter(
            recipient=user,
            created_at__gte=yesterday,
            is_read=False,
        ).order_by("-created_at")[:django_settings.DIGEST_MAX_NOTIFICATIONS]

        notifications = list(notifications)
        if not notifications:
            continue

        notif_count = len(notifications)

        # Build digest email
        lines = [f"You have {notif_count} unread notifications:\n"]
        for notif in notifications:
            lines.append(f"- {notif.title}: {notif.body[:100]}")

        try:
            email = EmailMessage(
                subject=f"Daily Digest: {notif_count} unread notifications",
                body="\n".join(lines),
                to=[user.email],
            )
            email.send(fail_silently=False)
            sent += 1
        except Exception as exc:
            logger.error("Failed to send digest to user %s: %s", user.id, str(exc))

    logger.info("Digest sender: sent %d digest emails", sent)
    return {"sent": sent}


@shared_task(name="apps.notifications.tasks_periodic.cleanup_old")
def cleanup_old():
    """
    Delete expired and old notifications.
    Runs daily at 3 AM via Celery Beat.
    """
    now = timezone.now()

    # Delete expired notifications
    expired_count = Notification.objects.filter(
        expires_at__lt=now,
    ).delete()[0]

    # Delete read notifications older than configured days
    cutoff = now - timedelta(days=django_settings.CLEANUP_READ_AFTER_DAYS)
    old_count = Notification.objects.filter(
        is_read=True,
        created_at__lt=cutoff,
    ).delete()[0]

    logger.info(
        "Cleanup: deleted %d expired, %d old read notifications",
        expired_count, old_count,
    )
    return {"expired_deleted": expired_count, "old_deleted": old_count}


@shared_task(name="apps.notifications.tasks_periodic.cleanup_fcm_tokens")
def cleanup_fcm_tokens():
    """
    Deactivate inactive FCM device tokens (no activity in 30 days).
    Runs daily at 4 AM via Celery Beat.
    """
    try:
        from fcm_django.models import FCMDevice

        cutoff = timezone.now() - timedelta(days=django_settings.CLEANUP_FCM_AFTER_DAYS)
        inactive = FCMDevice.objects.filter(
            active=True,
            date_created__lt=cutoff,
        )

        count = inactive.update(active=False)
        logger.info("FCM cleanup: deactivated %d inactive device tokens", count)
        return {"deactivated": count}

    except Exception as exc:
        logger.error("FCM cleanup error: %s", str(exc))
        return {"error": str(exc)}


@shared_task(name="apps.notifications.tasks_periodic.publish_metrics")
def publish_metrics():
    """
    Publish queue and delivery metrics (placeholder for Prometheus integration).
    Runs every 30 seconds via Celery Beat.
    """
    # Delivery status counts
    status_counts = (
        NotificationDelivery.objects.values("status", "channel")
        .annotate(count=Count("id"))
    )

    metrics = {}
    for entry in status_counts:
        key = f"{entry['channel']}_{entry['status']}"
        metrics[key] = entry["count"]

    # Unread count across all users
    total_unread = Notification.objects.filter(is_read=False).count()
    metrics["total_unread"] = total_unread

    logger.debug("Metrics published: %s", metrics)
    return metrics
