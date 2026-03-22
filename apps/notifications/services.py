import logging
from datetime import datetime, timedelta

from django.utils import timezone

from .models import Notification, NotificationDelivery, NotificationPreference

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def create_notification(validated_data):
        notification = Notification.objects.create(**validated_data)

        channels = notification.type.channels or ["inapp"]

        preference = NotificationPreference.objects.filter(
            user=notification.recipient
        ).first()

        enabled_channels = NotificationService._filter_channels(channels, preference)

        deliveries = []
        for channel in enabled_channels:
            deliveries.append(
                NotificationDelivery(
                    notification=notification,
                    channel=channel,
                    status=NotificationDelivery.Status.PENDING,
                )
            )

        if deliveries:
            NotificationDelivery.objects.bulk_create(deliveries)

        eta = NotificationService._get_quiet_hours_eta(preference)

        NotificationService._enqueue_delivery_tasks(
            notification, enabled_channels, eta=eta
        )

        return notification

    @staticmethod
    def _enqueue_delivery_tasks(notification, enabled_channels, eta=None):
        """Enqueue Celery tasks for each enabled delivery channel."""
        from .tasks import send_email, send_inapp, send_push

        notification_id = str(notification.id)

        task_map = {
            "email": send_email,
            "push": send_push,
            "inapp": send_inapp,
        }

        for channel in enabled_channels:
            task = task_map.get(channel)
            if task:
                try:
                    if eta:
                        task.apply_async(args=[notification_id], eta=eta)
                        logger.info(
                            "Scheduled %s task for notification %s at %s (quiet hours)",
                            channel, notification_id, eta.isoformat(),
                        )
                    else:
                        task.delay(notification_id)
                        logger.info(
                            "Enqueued %s task for notification %s",
                            channel, notification_id,
                        )
                except Exception as exc:
                    logger.error(
                        "Failed to enqueue %s task for notification %s: %s",
                        channel, notification_id, str(exc),
                    )

    @staticmethod
    def _get_quiet_hours_eta(preference):
        """
        Check if current time is within user's quiet hours.
        Returns ETA for after quiet hours end, or None.
        """
        if not preference:
            return None
        if not preference.quiet_hours_start or not preference.quiet_hours_end:
            return None

        now = timezone.now()
        current_time = now.time()
        start = preference.quiet_hours_start
        end = preference.quiet_hours_end

        in_quiet = False
        if start <= end:
            # Same day: e.g., 09:00 to 17:00
            in_quiet = start <= current_time <= end
        else:
            # Crosses midnight: e.g., 22:00 to 07:00
            in_quiet = current_time >= start or current_time <= end

        if not in_quiet:
            return None

        # Calculate ETA: next occurrence of quiet_hours_end
        eta_date = now.date()
        if start > end:
            # Quiet hours cross midnight (e.g., 22:00-07:00)
            if current_time >= start:
                # We're before midnight — end is tomorrow
                eta_date += timedelta(days=1)
            # else: we're after midnight — end is today (eta_date unchanged)

        eta = timezone.make_aware(
            datetime.combine(eta_date, end),
            timezone=now.tzinfo,
        )
        eta += timedelta(minutes=1)  # 1 min buffer after quiet hours

        logger.info("Quiet hours active, scheduling delivery at %s", eta.isoformat())
        return eta

    @staticmethod
    def _filter_channels(channels, preference):
        """Filter channels based on user preferences."""
        if not preference:
            return channels

        enabled = []
        channel_map = {
            "email": preference.email_enabled,
            "push": preference.push_enabled,
            "inapp": preference.inapp_enabled,
        }

        for channel in channels:
            if channel_map.get(channel, True):
                enabled.append(channel)

        return enabled

    @staticmethod
    def mark_as_read(notification):
        """Mark a single notification as read."""
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return notification

    @staticmethod
    def mark_all_read(user):
        """Mark all unread notifications as read for a user."""
        count = Notification.objects.filter(
            recipient=user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return count

    @staticmethod
    def get_unread_count(user):
        """Get unread notification count for a user."""
        return Notification.objects.filter(
            recipient=user, is_read=False
        ).count()
