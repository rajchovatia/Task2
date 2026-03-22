# FCM device management is handled by fcm-django package.
# The FCMDevice model is provided by fcm_django and is registered
# in INSTALLED_APPS via "fcm_django".
#
# Available model: fcm_django.models.FCMDevice
# Fields: user, registration_id, type, active, date_created
#
# Usage:
#   from fcm_django.models import FCMDevice
#   devices = FCMDevice.objects.filter(user=user, active=True)
#   devices.send_message(Message(...))
#
# API endpoints for device registration are in apps/devices/views.py
