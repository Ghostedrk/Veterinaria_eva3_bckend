"""Enlaces para tutores sin iniciar sesión: confirmar citas y firmar consentimientos.

Cada enlace lleva un token firmado con la SECRET_KEY de Django que identifica un solo
registro y vence a los 90 días. No se puede adivinar ni modificar sin invalidar la firma.
"""
import base64
import binascii

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Cita, Consentimiento
from .services import lock_agenda

SALT = "petcare.tutor"
MAX_AGE = 60 * 60 * 24 * 90
SIGNATURE_PREFIX = "data:image/png;base64,"
SIGNATURE_MAX_BYTES = 300 * 1024


def make_token(kind, pk):
    return signing.dumps([kind, pk], salt=SALT, compress=True)


def read_token(token, kind):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
    if isinstance(data, list) and len(data) == 2 and data[0] == kind and isinstance(data[1], int):
        return data[1]
    return None


def absolute(path, request=None):
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{settings.SITE_URL}{path}" if settings.SITE_URL else ""


def appointment_url(cita, request=None):
    return absolute(reverse("tutor-appointment", args=[make_token("cita", cita.pk)]), request)


def consent_url(consent, request=None):
    return absolute(reverse("tutor-consent", args=[make_token("consentimiento", consent.pk)]), request)


def send_appointment_link(cita, url):
    tutor = cita.mascota.tutor
    start = timezone.localtime(cita.inicio)
    sent = send_mail(
        f"Tu cita para {cita.mascota.nombre} · Veterinaria San Francisco",
        f"Hola, {tutor.nombre}.\n\n"
        f"{cita.mascota.nombre} tiene una cita el {start:%d/%m/%Y} a las {start:%H:%M} "
        f"con {cita.profesional.nombre} ({cita.motivo}).\n\n"
        f"Confirma o cancela tu hora en este enlace:\n{url}\n\nVeterinaria San Francisco",
        None, [tutor.email],
    )
    if sent != 1:
        raise RuntimeError("El transporte no aceptó el mensaje.")


@transaction.atomic
def respond_appointment(cita, *, accept):
    lock_agenda()
    cita = Cita.objects.select_for_update().get(pk=cita.pk)
    if cita.estado != Cita.Estado.AGENDADA or cita.inicio <= timezone.now():
        raise ValidationError("Esta cita ya no admite cambios. Llama a la clínica si necesitas ayuda.")
    cita.respuesta_tutor = Cita.Respuesta.CONFIRMADA if accept else Cita.Respuesta.CANCELADA
    cita.respondida_en = timezone.now()
    fields = ["respuesta_tutor", "respondida_en"]
    if not accept:
        cita.estado = Cita.Estado.CANCELADA
        fields.append("estado")
    cita.save(update_fields=fields)
    return cita


def validate_signature(data_url):
    if not data_url.startswith(SIGNATURE_PREFIX):
        raise ValidationError("Dibuja tu firma antes de autorizar.")
    try:
        raw = base64.b64decode(data_url[len(SIGNATURE_PREFIX):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("La firma no es válida. Vuelve a dibujarla.") from exc
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > SIGNATURE_MAX_BYTES:
        raise ValidationError("La firma no es válida. Vuelve a dibujarla.")


@transaction.atomic
def sign_consent(consent, *, accept, name, rut, signature, ip):
    consent = Consentimiento.objects.select_for_update().get(pk=consent.pk)
    if consent.estado != Consentimiento.Estado.PENDIENTE:
        raise ValidationError("Este consentimiento ya fue respondido.")
    name = " ".join(name.split())[:150]
    if len(name) < 3:
        raise ValidationError("Escribe tu nombre completo.")
    if accept:
        validate_signature(signature)
    consent.estado = Consentimiento.Estado.AUTORIZADO if accept else Consentimiento.Estado.RECHAZADO
    consent.firmante_nombre = name
    consent.firmante_rut = " ".join(rut.split())[:12]
    consent.firma = signature if accept else ""
    consent.respondido_en = timezone.now()
    consent.ip_firma = ip
    consent.save()
    return consent
