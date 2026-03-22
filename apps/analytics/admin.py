from django.contrib import admin

from .models import NotificationAnalytics


@admin.register(NotificationAnalytics)
class NotificationAnalyticsAdmin(admin.ModelAdmin):
    list_display = ["id", "notification", "event_type", "channel", "created_at"]
    list_filter = ["event_type", "channel"]
    readonly_fields = ["id", "created_at"]
