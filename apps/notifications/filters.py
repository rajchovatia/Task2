from django_filters import rest_framework as filters

from .models import Notification


class NotificationFilter(filters.FilterSet):
    is_read = filters.BooleanFilter(field_name="is_read")
    type = filters.NumberFilter(field_name="type_id")
    created_after = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Notification
        fields = ["is_read", "type", "created_after", "created_before"]
