import uuid

from django.db import models

from apps.notifications.models import Notification


class NotificationAnalytics(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="analytics"
    )
    event_type = models.CharField(
        max_length=20,
        help_text="delivered, opened, clicked",
    )
    channel = models.CharField(max_length=20)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_analytics"
        indexes = [
            models.Index(fields=["notification", "event_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.notification_id} — {self.event_type} [{self.channel}]"
