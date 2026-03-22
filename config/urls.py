from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.devices.urls")),
    path("api/v1/", include("apps.analytics.urls")),
    # Token authentication endpoint
    path("api/v1/auth/token/", obtain_auth_token, name="api_token_auth"),
    # Prometheus metrics endpoint (Phase 6)
    path("", include("django_prometheus.urls")),
]
