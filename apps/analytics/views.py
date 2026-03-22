from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.notifications.models import Notification

from .serializers import TrackEventSerializer
from .services import AnalyticsService


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def track_event(request):
    """
    POST /api/v1/analytics/track/
    Track a notification analytics event (delivered, opened, clicked).
    """
    serializer = TrackEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        notification = Notification.objects.get(
            id=serializer.validated_data["notification_id"]
        )
    except Notification.DoesNotExist:
        return Response(
            {"error": "Notification not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    AnalyticsService.track_event(
        notification=notification,
        event_type=serializer.validated_data["event_type"],
        channel=serializer.validated_data["channel"],
        metadata=serializer.validated_data.get("metadata", {}),
    )

    return Response({"status": "tracked"}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notification_stats(request, notification_id):
    """
    GET /api/v1/analytics/{notification_id}/
    Get analytics stats for a specific notification.
    """
    try:
        notification = Notification.objects.get(id=notification_id)
    except Notification.DoesNotExist:
        return Response(
            {"error": "Notification not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    stats = AnalyticsService.get_stats(notification)
    return Response(stats, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def channel_stats(request):
    """
    GET /api/v1/analytics/channels/?channel=email&hours=24
    Get aggregate stats for a channel.
    """
    channel = request.query_params.get("channel", "email")
    hours = int(request.query_params.get("hours", 24))

    stats = AnalyticsService.get_channel_stats(channel, hours)
    return Response(list(stats), status=status.HTTP_200_OK)
