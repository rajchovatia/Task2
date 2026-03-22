from rest_framework.pagination import CursorPagination

class NotificationCursorPagination(CursorPagination):
    page_size = 20
    ordering = "-created_at"
    cursor_query_param = "cursor"
