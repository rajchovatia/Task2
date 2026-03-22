from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .filters import NotificationFilter
from .idempotency import check_idempotency_redis, clear_idempotency_redis
from .models import Notification, NotificationPreference
from .pagination import NotificationCursorPagination
from .serializers import (
    BulkNotificationSerializer,
    CreateNotificationSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
)
from .services import NotificationService


class NotificationViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for notifications.

    list:    GET  /api/v1/notifications/
    create:  POST /api/v1/notifications/
    retrieve: GET /api/v1/notifications/{id}/
    """

    serializer_class = NotificationSerializer
    pagination_class = NotificationCursorPagination
    filterset_class = NotificationFilter
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch"]
    lookup_field = "id"

    def get_queryset(self):
        return (
            Notification.objects.filter(recipient=self.request.user)
            .select_related("type")
            .prefetch_related("deliveries")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return CreateNotificationSerializer
        if self.action == "bulk_create":
            return BulkNotificationSerializer
        return NotificationSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a notification with 3-layer idempotency:
        Layer 1: X-Idempotency-Key header
        Layer 2: Redis SET NX (fast duplicate check)
        Layer 3: DB UNIQUE constraint on idempotency_key
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Layer 1: Extract idempotency key from header or body
        idempotency_key = (
            request.headers.get("X-Idempotency-Key")
            or serializer.validated_data.get("idempotency_key")
        )

        if idempotency_key:
            serializer.validated_data["idempotency_key"] = idempotency_key

            # Layer 2: Redis SET NX — fast check
            is_new = check_idempotency_redis(idempotency_key)
            if not is_new:
                # Redis says duplicate — verify in DB (Layer 3)
                existing = Notification.objects.filter(
                    idempotency_key=idempotency_key
                ).first()
                if existing:
                    return Response(
                        NotificationSerializer(existing).data,
                        status=status.HTTP_200_OK,
                    )

        try:
            notification = NotificationService.create_notification(
                serializer.validated_data
            )
        except Exception:
            if idempotency_key:
                clear_idempotency_redis(idempotency_key)
            raise

        output_serializer = NotificationSerializer(notification)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request):
        """
        POST /api/v1/notifications/bulk/
        Create bulk notifications — fans out via Celery in batches.
        """
        serializer = BulkNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .tasks_bulk import fan_out_bulk_notifications

        # Convert validated_data to JSON-serializable dict
        bulk_data = {
            "type_id": serializer.validated_data["type"].id,
            "title": serializer.validated_data["title"],
            "body": serializer.validated_data.get("body", ""),
            "metadata": serializer.validated_data.get("metadata", {}),
            "recipient_ids": serializer.validated_data["recipient_ids"],
        }
        task = fan_out_bulk_notifications.delay(bulk_data)

        return Response(
            {
                "status": "accepted",
                "task_id": task.id,
                "message": (
                    f"Bulk notification queued for "
                    f"{len(serializer.validated_data['recipient_ids'])} recipients"
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["patch"], url_path="read")
    def mark_read(self, request, id=None):
        """PATCH /api/v1/notifications/{id}/read/"""
        notification = self.get_object()
        NotificationService.mark_as_read(notification)
        return Response(
            NotificationSerializer(notification).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["patch"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """PATCH /api/v1/notifications/mark-all-read/"""
        count = NotificationService.mark_all_read(request.user)
        return Response({"marked_read": count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """GET /api/v1/notifications/unread-count/"""
        count = NotificationService.get_unread_count(request.user)
        return Response({"count": count}, status=status.HTTP_200_OK)


class NotificationPreferenceViewSet(viewsets.GenericViewSet):
    """
    GET /api/v1/preferences/     — get user preferences
    PUT /api/v1/preferences/     — update user preferences
    """

    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        obj, _ = NotificationPreference.objects.get_or_create(user=self.request.user)
        return obj

    def list(self, request):
        """GET /api/v1/preferences/"""
        preference = self.get_object()
        serializer = self.get_serializer(preference)
        return Response(serializer.data)

    def update(self, request):
        """PUT /api/v1/preferences/"""
        preference = self.get_object()
        serializer = self.get_serializer(preference, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """GET /api/v1/health/ — basic health check."""
    return Response({"status": "ok"}, status=status.HTTP_200_OK)
