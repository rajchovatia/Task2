import uuid
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.db import models

User = get_user_model()


class NotificationType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    template = models.TextField(blank=True)
    channels = ArrayField(
        models.CharField(max_length=20),
        default=list,
        help_text="List of channels: email, push, inapp",
    )
    priority = models.SmallIntegerField(
        default=5,
        help_text="Priority 1 (highest) to 10 (lowest)",
    )

    class Meta:
        db_table = "notification_types"

    def __str__(self):
        return self.name


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.ForeignKey(NotificationType, on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    body = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "-created_at"],
                condition=models.Q(is_read=False),
                name="idx_notif_user_unread",
            ),
            models.Index(
                fields=["expires_at"],
                condition=models.Q(expires_at__isnull=False),
                name="idx_notif_expires",
            ),
        ]

    def __str__(self):
        return f"{self.title} → {self.recipient}"


class NotificationDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        DELIVERED = "delivered"
        FAILED = "failed"
        BOUNCED = "bounced"

    class Channel(models.TextChoices):
        EMAIL = "email"
        PUSH = "push"
        INAPP = "inapp"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    provider_id = models.CharField(max_length=255, blank=True, null=True)
    attempts = models.SmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_deliveries"
        unique_together = [("notification", "channel")]
        indexes = [
            models.Index(
                fields=["status", "channel"],
                condition=models.Q(status__in=["pending", "failed"]),
                name="idx_delivery_status",
            ),
        ]

    def __str__(self):
        return f"{self.notification.title} [{self.channel}] → {self.status}"


class NotificationPreference(models.Model):
    class DigestMode(models.TextChoices):
        INSTANT = "instant"
        HOURLY = "hourly"
        DAILY = "daily"

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    inapp_enabled = models.BooleanField(default=True)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    digest_mode = models.CharField(
        max_length=20,
        choices=DigestMode.choices,
        default=DigestMode.INSTANT,
    )
    channel_overrides = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "notification_preferences"

    def __str__(self):
        return f"Preferences for {self.user}"
