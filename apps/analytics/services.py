import logging

from .models import NotificationAnalytics

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Track notification delivery analytics events."""

    @staticmethod
    def track_event(notification, event_type, channel, metadata=None):
        """
        Record an analytics event.

        Args:
            notification: Notification model instance
            event_type: "delivered", "opened", "clicked", "failed"
            channel: "email", "push", "inapp"
            metadata: Optional dict with extra data (device info, click URL, etc.)
        """
        try:
            return NotificationAnalytics.objects.create(
                notification=notification,
                event_type=event_type,
                channel=channel,
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.error(
                "Failed to track analytics for notification %s: %s",
                notification.id, str(exc),
            )
            return None

    @staticmethod
    def get_stats(notification):
        """Get analytics stats for a single notification."""
        events = NotificationAnalytics.objects.filter(
            notification=notification
        ).values("event_type", "channel")

        stats = {}
        for event in events:
            key = f"{event['channel']}_{event['event_type']}"
            stats[key] = stats.get(key, 0) + 1

        return stats

    @staticmethod
    def get_channel_stats(channel, hours=24):
        """Get aggregate stats for a channel over the last N hours."""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count

        since = timezone.now() - timedelta(hours=hours)

        return (
            NotificationAnalytics.objects.filter(
                channel=channel,
                created_at__gte=since,
            )
            .values("event_type")
            .annotate(count=Count("id"))
            .order_by("event_type")
        )
