from django.contrib import admin

from .models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
)


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "channels", "priority"]
    search_fields = ["name"]


class NotificationDeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    readonly_fields = [
        "id",
        "channel",
        "status",
        "provider_id",
        "attempts",
        "last_attempt_at",
        "error_message",
        "created_at",
    ]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "recipient", "type", "is_read", "created_at"]
    list_filter = ["is_read", "type", "created_at"]
    search_fields = ["title", "body", "recipient__username"]
    readonly_fields = ["id", "created_at"]
    inlines = [NotificationDeliveryInline]


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "notification",
        "channel",
        "status",
        "attempts",
        "created_at",
    ]
    list_filter = ["channel", "status"]


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "email_enabled",
        "push_enabled",
        "inapp_enabled",
        "digest_mode",
    ]
    list_filter = ["digest_mode"]
