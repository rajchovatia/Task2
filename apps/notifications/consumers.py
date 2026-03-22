import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from prometheus_client import Gauge

logger = logging.getLogger(__name__)

# Prometheus metric for active WebSocket connections
websocket_connections_active = Gauge(
    "django_websocket_connections_active",
    "Number of active WebSocket connections",
)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time notification delivery.

    Clients connect to ws/notifications/ with a valid token.
    On connect, they join a user-specific group: notifications_{user_id}
    Server can push notifications and unread count updates to connected clients.
    """

    async def connect(self):
        self.user = self.scope["user"]

        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = f"notifications_{self.user.id}"

        # Join user-specific notification group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Track active WebSocket connections
        websocket_connections_active.inc()

        # Send unread count on connect
        count = await self.get_unread_count()
        await self.send_json({"type": "unread_count", "count": count})

    async def disconnect(self, close_code):
        # Track active WebSocket connections
        websocket_connections_active.dec()

        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive_json(self, content, **kwargs):
        """Handle incoming messages from the client."""
        msg_type = content.get("type")

        if msg_type == "mark_read":
            notification_id = content.get("notification_id")
            if notification_id:
                await self.mark_notification_read(notification_id)
                count = await self.get_unread_count()
                await self.send_json({"type": "unread_count", "count": count})

        elif msg_type == "mark_all_read":
            await self.mark_all_notifications_read()
            await self.send_json({"type": "unread_count", "count": 0})

    # ── Group message handlers (called via channel_layer.group_send) ──

    async def notification_send(self, event):
        """Send a new notification to the client."""
        await self.send_json(event["data"])

    async def unread_count_update(self, event):
        """Send updated unread count to the client."""
        await self.send_json({"type": "unread_count", "count": event["count"]})

    # ── Database helpers ──

    @database_sync_to_async
    def get_unread_count(self):
        from .models import Notification

        return Notification.objects.filter(
            recipient=self.user, is_read=False
        ).count()

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from .models import Notification
        from .services import NotificationService

        try:
            notification = Notification.objects.get(
                id=notification_id, recipient=self.user
            )
            NotificationService.mark_as_read(notification)
        except Notification.DoesNotExist:
            logger.warning(
                "Notification %s not found for user %s (mark_read via WS)",
                notification_id, self.user.id,
            )

    @database_sync_to_async
    def mark_all_notifications_read(self):
        from .services import NotificationService

        NotificationService.mark_all_read(self.user)
