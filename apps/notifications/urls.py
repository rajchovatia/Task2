from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path(
        "preferences/",
        views.NotificationPreferenceViewSet.as_view(
            {"get": "list", "put": "update"}
        ),
        name="preferences",
    ),
    path("", include(router.urls)),
]
