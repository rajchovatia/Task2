from rest_framework import serializers

from .models import NotificationAnalytics


class NotificationAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationAnalytics
        fields = ["id", "notification", "event_type", "channel", "metadata", "created_at"]
        read_only_fields = ["id", "created_at"]


class TrackEventSerializer(serializers.Serializer):
    notification_id = serializers.UUIDField()
    event_type = serializers.ChoiceField(
        choices=["delivered", "opened", "clicked", "failed"]
    )
    channel = serializers.ChoiceField(choices=["email", "push", "inapp"])
    metadata = serializers.JSONField(required=False, default=dict)
