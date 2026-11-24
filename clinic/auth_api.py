"""Autenticación JWT, perfil del usuario y estado de la API."""
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from . import roles


class LoginThrottle(ScopedRateThrottle):
    scope_attr = "throttle_scope"


class LoginView(TokenObtainPairView):
    """Entrega un par de tokens (access y refresh) a partir de usuario y contraseña."""

    throttle_classes = [LoginThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    """Rota el refresh token y entrega un access token nuevo."""


class LogoutView(TokenBlacklistView):
    """Invalida el refresh token (lista negra) al cerrar sesión."""


@extend_schema(responses=inline_serializer("Perfil", {
    "id": serializers.IntegerField(), "username": serializers.CharField(),
    "nombre": serializers.CharField(), "rol": serializers.CharField(),
    "puede_gestionar_profesionales": serializers.BooleanField(),
}))
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """Perfil y rol del usuario autenticado por el token."""
    user = request.user
    return Response({
        "id": user.pk, "username": user.username, "nombre": user.get_full_name() or user.username,
        "rol": roles.role_name(user), "es_personal": user.is_staff,
        "puede_gestionar_profesionales": roles.is_full_staff(user),
    })


@extend_schema(auth=[], responses=inline_serializer("Salud", {
    "status": serializers.CharField(), "database": serializers.CharField()}))
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def health(request):
    """Estado público de la API y de la conexión a PostgreSQL (sin datos sensibles)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return Response({"status": "ok", "database": connection.vendor})
