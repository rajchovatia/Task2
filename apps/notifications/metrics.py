"""
Custom Prometheus metrics for the notification system.

Exposes delivery and task metrics via a custom collector that queries
the database. This runs in the API/WS process where /metrics is scraped.
"""

from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
from prometheus_client import Gauge


class NotificationMetricsCollector:
    """
    Custom Prometheus collector that exposes notification delivery metrics
    by querying the database on each scrape.
    """

    def collect(self):
        try:
            from django.db.models import Count
            from .models import Notification, NotificationDelivery

            # Celery task metrics from delivery status
            # sent = succeeded, failed = failed, pending = in-progress/retrying
            status_counts = (
                NotificationDelivery.objects
                .values("status", "channel")
                .annotate(count=Count("id"))
            )

            succeeded = GaugeMetricFamily(
                "celery_task_succeeded_total",
                "Total Celery tasks that succeeded (delivered notifications)",
                labels=["channel"],
            )
            failed = GaugeMetricFamily(
                "celery_task_failed_total",
                "Total Celery tasks that failed",
                labels=["channel"],
            )
            retried = GaugeMetricFamily(
                "celery_task_retried_total",
                "Total Celery tasks retried (pending deliveries)",
                labels=["channel"],
            )

            channel_stats = {}
            for entry in status_counts:
                ch = entry["channel"]
                st = entry["status"]
                cnt = entry["count"]
                if ch not in channel_stats:
                    channel_stats[ch] = {"sent": 0, "failed": 0, "pending": 0}
                channel_stats[ch][st] = cnt

            for ch, counts in channel_stats.items():
                succeeded.add_metric([ch], counts.get("sent", 0))
                failed.add_metric([ch], counts.get("failed", 0))
                retried.add_metric([ch], counts.get("pending", 0))

            yield succeeded
            yield failed
            yield retried

            # Notifications created total
            notif_total = GaugeMetricFamily(
                "notifications_created_total",
                "Total notifications created",
                labels=["type"],
            )
            type_counts = (
                Notification.objects
                .values("type__name")
                .annotate(count=Count("id"))
            )
            for entry in type_counts:
                notif_total.add_metric(
                    [entry["type__name"] or "unknown"],
                    entry["count"],
                )
            yield notif_total

            # Total unread
            unread = Notification.objects.filter(is_read=False).count()
            unread_gauge = GaugeMetricFamily(
                "notifications_unread_total",
                "Total unread notifications across all users",
            )
            unread_gauge.add_metric([], unread)
            yield unread_gauge

        except Exception:
            pass


def register_metrics():
    """Register the custom collector. Safe to call multiple times."""
    try:
        REGISTRY.register(NotificationMetricsCollector())
    except ValueError:
        pass  # Already registered
