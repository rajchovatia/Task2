import bleach
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
)


def _sanitize(value):
    if isinstance(value, str):
        return bleach.clean(value, tags=[], strip=True)
    return value


class NotificationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationType
        fields = ["id", "name", "template", "channels", "priority"]


class NotificationDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationDelivery
        fields = [
            "id",
            "channel",
            "status",
            "provider_id",
            "attempts",
            "last_attempt_at",
            "error_message",
            "created_at",
        ]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    type_name = serializers.CharField(source="type.name", read_only=True)
    deliveries = NotificationDeliverySerializer(many=True, read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "idempotency_key",
            "recipient",
            "type",
            "type_name",
            "title",
            "body",
            "metadata",
            "is_read",
            "read_at",
            "created_at",
            "expires_at",
            "deliveries",
        ]
        read_only_fields = ["id", "is_read", "read_at", "created_at"]


class CreateNotificationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Notification
        fields = [
            "idempotency_key",
            "recipient",
            "type",
            "title",
            "body",
            "metadata",
            "expires_at",
        ]

    def validate_idempotency_key(self, value):
        if value and Notification.objects.filter(idempotency_key=value).exists():
            raise serializers.ValidationError("Notification with this idempotency key already exists.")
        return value

    def validate_title(self, value):
        return _sanitize(value)

    def validate_body(self, value):
        return _sanitize(value)

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be a JSON object (dict).")
        return value

    def validate_expires_at(self, value):
        if value and value < timezone.now():
            raise serializers.ValidationError("expires_at cannot be in the past.")
        return value


class MarkReadSerializer(serializers.Serializer):
    pass


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "email_enabled",
            "push_enabled",
            "inapp_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "digest_mode",
            "channel_overrides",
        ]

    def validate(self, data):
        start = data.get("quiet_hours_start", self.instance.quiet_hours_start if self.instance else None)
        end = data.get("quiet_hours_end", self.instance.quiet_hours_end if self.instance else None)
        if (start is None) != (end is None):
            raise serializers.ValidationError(
                {"quiet_hours_start": "Both quiet_hours_start and quiet_hours_end must be set together, or both null."}
            )
        return data


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField(read_only=True)


class BulkNotificationSerializer(serializers.Serializer):

    recipient_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=100000,
    )
    type = serializers.PrimaryKeyRelatedField(queryset=NotificationType.objects.all())
    title = serializers.CharField(max_length=500)
    body = serializers.CharField(required=False, default="")
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_title(self, value):
        return _sanitize(value)

    def validate_body(self, value):
        return _sanitize(value)

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be a JSON object (dict).")
        return value
