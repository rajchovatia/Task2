from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token


@database_sync_to_async
def get_user_from_token(token_key):
    """Look up user by DRF auth token."""
    try:
        token = Token.objects.select_related("user").get(key=token_key)
        return token.user
    except Token.DoesNotExist:
        return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    """
    WebSocket authentication middleware.

    Accepts token via:
    1. Query string: ws://host/ws/notifications/?token=<token_key>
    2. First message after connect (handled in consumer)

    Uses DRF's Token model (rest_framework.authtoken).
    """

    async def __call__(self, scope, receive, send):
        # Parse token from query string
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token_key = query_params.get("token", [None])[0]

        if token_key:
            scope["user"] = await get_user_from_token(token_key)
        else:
            # Fall back to session auth (Django's AuthMiddleware)
            # This wraps the inner application with session-based auth
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    """Convenience wrapper: session auth + token auth."""
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))
