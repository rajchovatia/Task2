from django.db import transaction
from fcm_django.models import FCMDevice
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .serializers import FCMDeviceSerializer


class FCMDeviceViewSet(ModelViewSet):
    """
    Register, list, and unregister FCM device tokens.
    POST   /api/v1/devices/          — Register a device token
    GET    /api/v1/devices/          — List user's devices
    DELETE /api/v1/devices/{id}/     — Unregister a device
    """

    serializer_class = FCMDeviceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        return FCMDevice.objects.filter(user=self.request.user, active=True)

    @transaction.atomic
    def perform_create(self, serializer):
        registration_id = serializer.validated_data.get("registration_id")
        FCMDevice.objects.filter(
            registration_id=registration_id
        ).update(active=False)

        serializer.save(user=self.request.user, active=True)

    def destroy(self, request, *args, **kwargs):
        device = self.get_object()
        device.active = False
        device.save(update_fields=["active"])
        return Response(status=status.HTTP_204_NO_CONTENT)
