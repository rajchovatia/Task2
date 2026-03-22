from fcm_django.models import FCMDevice
from rest_framework import serializers


class FCMDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FCMDevice
        fields = ["id", "registration_id", "type", "active", "date_created"]
        read_only_fields = ["id", "date_created"]
