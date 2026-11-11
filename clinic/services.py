from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.utils import timezone

from .models import Atencion, Cita, Disponibilidad, Insumo, Mascota, Movimiento, Profesional, Recordatorio

AGENDA_MODELS = (Cita, Disponibilidad)
REMINDER_DATE_ERROR = "La anticipación o el intervalo exceden el rango de fechas."


def lock_agenda():
    # Serialize the clinic's calendar changes on PostgreSQL. SQLite demo
    # transactions use BEGIN IMMEDIATE, which already serializes writers.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [510427])


def validate_appointment(obj):
    if obj.estado == Cita.Estado.CANCELADA:
        return
    inside_window = Disponibilidad.objects.filter(
        profesional=obj.profesional, inicio__lte=obj.inicio, fin__gte=obj.fin
    ).exists()
    if not inside_window:
        raise ValidationError("El horario debe quedar dentro de un bloque del profesional.")
    clashes = Cita.objects.filter(inicio__lt=obj.fin, fin__gt=obj.inicio).exclude(
        models.Q(pk=obj.pk) | models.Q(estado=Cita.Estado.CANCELADA)
    )
    if clashes.filter(profesional=obj.profesional).exists():
        raise ValidationError("El profesional ya tiene una cita en ese horario.")
    if clashes.filter(mascota=obj.mascota).exists():
        raise ValidationError("La mascota ya tiene una cita en ese horario.")


def affected_appointments(old_window):
    return Cita.objects.filter(
        profesional=old_window.profesional, inicio__gte=old_window.inicio,
        fin__lte=old_window.fin, estado=Cita.Estado.AGENDADA,
    )


def validate_window(obj):
    overlapping = Disponibilidad.objects.filter(
        profesional=obj.profesional, inicio__lt=obj.fin, fin__gt=obj.inicio
    ).exclude(pk=obj.pk)
    if overlapping.exists():
        raise ValidationError("El profesional ya tiene disponibilidad registrada en ese tramo.")
    if obj.pk:
        previous = Disponibilidad.objects.get(pk=obj.pk)
        affected = affected_appointments(previous).exclude(
            profesional=obj.profesional, inicio__gte=obj.inicio, fin__lte=obj.fin
        )
        if affected.exists():
            raise ValidationError("Reprograma las citas agendadas antes de cambiar este bloque.")


def reminder_send_date(target, lead_days):
    try:
        return target - timedelta(days=lead_days)
    except OverflowError as exc:
        raise ValidationError(REMINDER_DATE_ERROR) from exc


INACTIVE_ERROR = "El profesional está inactivo. Elige otro o reactívalo primero."


def validate_professional_is_active(obj):
    """New work can't be assigned to an inactive professional; history stays editable."""
    if not obj.profesional_id or obj.profesional.activo:
        return
    if obj.pk:
        previous = type(obj).objects.filter(pk=obj.pk).values_list("profesional_id", flat=True).first()
        if previous == obj.profesional_id:
            return
    raise ValidationError({"profesional": INACTIVE_ERROR})


def upcoming_appointments(professional):
    return Cita.objects.filter(profesional=professional, estado=Cita.Estado.AGENDADA, fin__gt=timezone.now())


def validate_rules(obj):
    """Business rules shared by the panel, the API and Django Admin."""
    if isinstance(obj, (Cita, Disponibilidad, Atencion)):
        validate_professional_is_active(obj)
    if isinstance(obj, Profesional) and obj.pk and not obj.activo:
        pending = upcoming_appointments(obj).count()
        if pending:
            raise ValidationError(
                f"{obj.nombre} tiene {pending} cita(s) agendada(s) por delante. "
                "Reprográmalas o cancélalas antes de desactivarlo."
            )
    if isinstance(obj, Mascota) and obj.nacimiento and obj.nacimiento > timezone.localdate():
        raise ValidationError({"nacimiento": "La fecha de nacimiento no puede estar en el futuro."})
    if isinstance(obj, Cita):
        validate_appointment(obj)
    if isinstance(obj, Disponibilidad):
        validate_window(obj)
    if isinstance(obj, Recordatorio) and obj.repetir_dias:
        try:
            obj.fecha_objetivo + timedelta(days=obj.repetir_dias)
        except OverflowError as exc:
            raise ValidationError(REMINDER_DATE_ERROR) from exc
    if (isinstance(obj, Movimiento) and obj.tipo == Movimiento.Tipo.SALIDA
            and not Insumo.objects.filter(pk=obj.insumo_id, stock__gte=obj.cantidad).exists()):
        raise ValidationError({"cantidad": "El movimiento dejaría el stock fuera del rango permitido."})


@transaction.atomic
def save_record(obj, *, user, changed_fields=None):
    if isinstance(obj, AGENDA_MODELS):
        lock_agenda()
    if obj.pk:
        previous = type(obj).objects.select_for_update().get(pk=obj.pk)
        if isinstance(previous, Recordatorio) and previous.enviado_en:
            raise ValidationError("El recordatorio ya fue enviado y forma parte del historial.")
        if changed_fields is not None:
            for field in changed_fields:
                setattr(previous, field, getattr(obj, field))
            obj = previous
    if isinstance(obj, Recordatorio) and obj.fecha_objetivo is not None:
        obj.enviar_el = reminder_send_date(obj.fecha_objetivo, obj.anticipacion_dias)
    if isinstance(obj, Movimiento):
        obj.registrado_por = user

    obj.full_clean()
    validate_rules(obj)
    if isinstance(obj, Movimiento):
        items = Insumo.objects.filter(pk=obj.insumo_id)
        delta = obj.cantidad
        if obj.tipo == Movimiento.Tipo.SALIDA:
            items = items.filter(stock__gte=obj.cantidad)
            delta = -obj.cantidad
        else:
            maximum = connection.ops.integer_field_range("PositiveIntegerField")[1]
            items = items.filter(stock__lte=maximum - obj.cantidad)
        if not items.update(stock=models.F("stock") + delta):
            raise ValidationError({"cantidad": "El movimiento dejaría el stock fuera del rango permitido."})
    if isinstance(obj, Insumo) and obj.pk:
        # The inventory ledger owns stock. A concurrent movement must never
        # be overwritten when editing product metadata.
        obj.save(update_fields=["codigo", "nombre", "categoria", "unidad", "minimo"])
    else:
        obj.save(force_update=obj.pk is not None)
    return obj


@transaction.atomic
def delete_record(obj):
    if isinstance(obj, AGENDA_MODELS):
        lock_agenda()
    obj = type(obj).objects.select_for_update().get(pk=obj.pk)
    if isinstance(obj, Disponibilidad) and affected_appointments(obj).exists():
        raise ValidationError("Reprograma o cancela las citas agendadas antes de quitar este bloque.")
    if isinstance(obj, Recordatorio) and obj.enviado_en:
        raise ValidationError("El recordatorio enviado forma parte del historial.")
    obj.delete()



@transaction.atomic
def set_professional_active(professional, active, *, user):
    """Soft delete: deactivating keeps history and frees the professional's future availability."""
    lock_agenda()
    professional = Profesional.objects.select_for_update().get(pk=professional.pk)
    professional.activo = active
    professional = save_record(professional, user=user, changed_fields={"activo"})
    if not active:
        Disponibilidad.objects.filter(profesional=professional, fin__gt=timezone.now()).delete()
    return professional
