"""Roles del equipo.

- Jefatura (superusuario): todo, incluidas las cuentas.
- Administración (personal): toda la operación de la clínica.
- Recepción (personal del grupo "Recepción"): agenda, tutores, mascotas, fichas,
  recordatorios e inventario; no gestiona profesionales, no hace compras y no
  entra a Django Admin.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

RECEPCION = "Recepción"
ROLES = (("administracion", "Administración"), ("recepcion", "Recepción"))


def is_reception(user):
    if not user.is_authenticated or user.is_superuser:
        return False
    cached = getattr(user, "_petcare_reception", None)
    if cached is None:
        cached = user.groups.filter(name=RECEPCION).exists()
        user._petcare_reception = cached
    return cached


def is_full_staff(user):
    """Jefatura o Administración."""
    return user.is_active and user.is_staff and not is_reception(user)


can_manage_professionals = can_purchase = can_use_admin = is_full_staff

# Recursos del panel y la API que Recepción solo puede consultar.
READ_ONLY_FOR_RECEPTION = {"profesionales"}


def role_name(user):
    if user.is_superuser:
        return "Jefatura"
    return "Recepción" if is_reception(user) else "Administración"


def ui(request):
    """Context processor: qué opciones mostrar en las plantillas."""
    user = request.user
    if not user.is_authenticated:
        return {}
    full = is_full_staff(user)
    return {
        "role_name": role_name(user),
        "can_manage_professionals": full,
        "can_purchase": full,
        "can_use_admin": full,
    }


class RolePermission(BasePermission):
    """API: Recepción solo lee los recursos restringidos."""

    message = "Tu rol no permite modificar este recurso."

    def has_permission(self, request, view):
        slug = getattr(view, "basename", None)
        if slug in READ_ONLY_FOR_RECEPTION and request.method not in SAFE_METHODS:
            return is_full_staff(request.user)
        return True
