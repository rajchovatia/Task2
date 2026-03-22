from rest_framework.routers import DefaultRouter

from .views import FCMDeviceViewSet

router = DefaultRouter()
router.register("devices", FCMDeviceViewSet, basename="devices")

urlpatterns = router.urls
