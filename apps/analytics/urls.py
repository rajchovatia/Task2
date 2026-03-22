from django.urls import path

from . import views

urlpatterns = [
    path("analytics/track/", views.track_event, name="analytics-track"),
    path(
        "analytics/<uuid:notification_id>/",
        views.notification_stats,
        name="analytics-notification",
    ),
    path("analytics/channels/", views.channel_stats, name="analytics-channels"),
]
