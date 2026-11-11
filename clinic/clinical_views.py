import mimetypes
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from . import roles, tutor
from .models import Adjunto, Atencion, Cita, Consentimiento, Mascota
from .resources import ActiveProfessionalForm
from .views import staff_required

MAGIC = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
}


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Adjunto
        fields = ("tipo", "descripcion", "archivo")
        widgets = {"archivo": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png,.webp"})}

    def clean_archivo(self):
        upload = self.cleaned_data["archivo"]
        if upload.size > settings.ATTACHMENT_MAX_BYTES:
            raise ValidationError("El archivo supera los 10 MB.")
        ext = upload.name.lower().rsplit(".", 1)[-1]
        head = upload.read(12)
        upload.seek(0)
        if not any(head.startswith(sig) for sig in MAGIC.get(ext, ())) or (ext == "webp" and head[8:12] != b"WEBP"):
            raise ValidationError("El contenido no corresponde a un PDF o imagen válida.")
        return upload


CONSENT_RISKS = {
    "cirugia": "Riesgo anestésico, sangrado, infección de la herida, dehiscencia de puntos y, en casos "
               "excepcionales, muerte. El equipo informará cualquier complicación de inmediato.",
    "anestesia": "Reacciones adversas a los fármacos, depresión respiratoria o cardiovascular, hipotermia "
                 "y, en casos excepcionales, muerte.",
    "eutanasia": "Procedimiento irreversible. Se realiza bajo sedación profunda para evitar dolor y angustia.",
    "otro": "",
}


class ConsentForm(ActiveProfessionalForm):
    class Meta:
        model = Consentimiento
        fields = ("mascota", "profesional", "procedimiento", "fecha_procedimiento", "descripcion", "riesgos")
        widgets = {"fecha_procedimiento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}


def weight_chart(pet):
    rows = list(pet.atenciones.filter(peso_kg__isnull=False).order_by("fecha", "pk").values_list("fecha", "peso_kg"))
    if not rows:
        return None
    width, height, left, right, top, bottom = 640, 230, 52, 18, 16, 34
    weights = [float(w) for _, w in rows]
    margin = max((max(weights) - min(weights)) * 0.2, 0.5)
    low, high = max(0.0, min(weights) - margin), max(weights) + margin
    first, last = rows[0][0].toordinal(), rows[-1][0].toordinal()
    span = last - first

    def x(day):
        if not span:
            return left + (width - left - right) / 2
        return left + (day.toordinal() - first) / span * (width - left - right)

    def y(weight):
        return top + (high - weight) / (high - low) * (height - top - bottom)

    def coord(value):
        # Texto con punto decimal: Django localiza los float en español con coma y el SVG los rechaza.
        return f"{value:.1f}"

    dots = [{"x": coord(x(d)), "y": coord(y(w)), "peso": w, "fecha": d} for d, w in zip((r[0] for r in rows), weights)]
    ticks = [low + (high - low) * i / 4 for i in range(5)]
    picks = [(dots[0], "start" if len(dots) > 1 else "middle")]
    if len(dots) > 2:
        picks.append((dots[len(dots) // 2], "middle"))
    if len(dots) > 1:
        picks.append((dots[-1], "end"))
    labels = [{"x": d["x"], "fecha": d["fecha"], "anchor": anchor} for d, anchor in picks]
    return {
        "width": width, "height": height, "left": left, "right": width - right, "bottom": height - bottom,
        "points": " ".join(f"{d['x']},{d['y']}" for d in dots), "dots": dots,
        "yticks": [{"y": coord(y(t)), "label": f"{t:.1f}".replace(".", ",")} for t in ticks],
        "xlabels": labels, "last": weights[-1], "change": round(weights[-1] - weights[0], 2), "count": len(dots),
    }


def detail_extras(request, obj):
    """Secciones extra del detalle genérico según el tipo de registro."""
    if isinstance(obj, Mascota):
        return {
            "weight": weight_chart(obj),
            "consents": obj.consentimientos.select_related("profesional")[:10],
        }
    if isinstance(obj, Atencion):
        return {"attachments": obj.adjuntos.select_related("subido_por"), "attachment_form": AttachmentForm()}
    if isinstance(obj, Cita):
        return {"tutor_link": tutor.appointment_url(obj, request) if obj.estado == Cita.Estado.AGENDADA else ""}
    return {}


# Adjuntos -------------------------------------------------------------------

@staff_required
@require_POST
def attachment_upload(request, pk):
    visit = get_object_or_404(Atencion, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        upload = form.cleaned_data["archivo"]
        ext = upload.name.lower().rsplit(".", 1)[-1]
        attachment.nombre_original = upload.name[-150:]
        attachment.tamano = upload.size
        attachment.archivo.name = f"{uuid4().hex}.{ext}"  # Nombre impredecible en disco.
        attachment.atencion = visit
        attachment.subido_por = request.user
        attachment.save()
        messages.success(request, "Archivo adjuntado a la ficha.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("record-detail", slug="atenciones", pk=pk)


@staff_required
@require_safe
def attachment_file(request, pk):
    attachment = get_object_or_404(Adjunto, pk=pk)
    try:
        handle = attachment.archivo.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    content_type = mimetypes.guess_type(attachment.nombre_original)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type, as_attachment=request.GET.get("descargar") == "1",
                            filename=attachment.nombre_original)
    response["Cache-Control"] = "private, no-store"
    return response


@staff_required
@require_POST
def attachment_delete(request, pk):
    if not roles.is_full_staff(request.user):
        raise PermissionDenied
    attachment = get_object_or_404(Adjunto, pk=pk)
    visit_pk = attachment.atencion_id
    with transaction.atomic():
        attachment.delete()
        transaction.on_commit(lambda: attachment.archivo.delete(save=False))
    messages.success(request, "Adjunto eliminado.")
    return redirect("record-detail", slug="atenciones", pk=visit_pk)


# Citas: enlace del tutor ---------------------------------------------------

@staff_required
@require_POST
def appointment_send_link(request, pk):
    cita = get_object_or_404(Cita.objects.select_related("mascota__tutor", "profesional"), pk=pk)
    if cita.estado != Cita.Estado.AGENDADA:
        messages.error(request, "Solo se envía el enlace de citas agendadas.")
    else:
        try:
            tutor.send_appointment_link(cita, tutor.appointment_url(cita, request))
        except (OSError, RuntimeError):
            messages.error(request, "No se pudo enviar el correo. Copia el enlace y envíalo por otro medio.")
        else:
            cita.aviso_enviado_en = timezone.now()
            cita.save(update_fields=["aviso_enviado_en"])
            messages.success(request, f"Enlace enviado a {cita.mascota.tutor.email}.")
    return redirect("record-detail", slug="citas", pk=pk)


@require_http_methods(["GET", "HEAD", "POST"])
def tutor_appointment(request, token):
    pk = tutor.read_token(token, "cita")
    if pk is None:
        return render(request, "clinic/tutor_invalid.html", status=404)
    cita = get_object_or_404(Cita.objects.select_related("mascota__tutor", "profesional"), pk=pk)
    error = ""
    if request.method == "POST":
        try:
            cita = tutor.respond_appointment(cita, accept=request.POST.get("respuesta") == "confirmar")
        except ValidationError as exc:
            error = " ".join(exc.messages)
    editable = cita.estado == Cita.Estado.AGENDADA and cita.inicio > timezone.now()
    return render(request, "clinic/tutor_appointment.html", {"cita": cita, "editable": editable, "error": error})


# Consentimientos -------------------------------------------------------------

@staff_required
@require_http_methods(["GET", "HEAD", "POST"])
def consent_create(request):
    initial = {"fecha_procedimiento": timezone.localdate()}
    if request.GET.get("mascota", "").isdigit():
        initial["mascota"] = request.GET["mascota"]
    procedure = request.GET.get("procedimiento", "cirugia")
    initial["procedimiento"] = procedure
    initial["riesgos"] = CONSENT_RISKS.get(procedure, "")
    form = ConsentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        consent = form.save(commit=False)
        consent.creado_por = request.user
        consent.save()
        messages.success(request, "Consentimiento creado. Compártelo con el tutor para que lo firme.")
        return redirect("consent-detail", pk=consent.pk)
    return render(request, "clinic/consent_form.html", {"form": form, "risks": CONSENT_RISKS})


@staff_required
@require_safe
def consent_list(request):
    consents = Consentimiento.objects.select_related("mascota__tutor", "profesional")
    state = request.GET.get("estado", "")
    if state in Consentimiento.Estado.values:
        consents = consents.filter(estado=state)
    return render(request, "clinic/consent_list.html", {
        "consents": consents[:100], "state": state, "states": Consentimiento.Estado.choices,
    })


@staff_required
@require_safe
def consent_detail(request, pk):
    consent = get_object_or_404(Consentimiento.objects.select_related("mascota__tutor", "profesional", "creado_por"), pk=pk)
    return render(request, "clinic/consent_detail.html", {
        "consent": consent, "print": request.GET.get("imprimir") == "1",
        "tutor_link": tutor.consent_url(consent, request) if consent.estado == Consentimiento.Estado.PENDIENTE else "",
    })


@require_http_methods(["GET", "HEAD", "POST"])
def tutor_consent(request, token):
    pk = tutor.read_token(token, "consentimiento")
    if pk is None:
        return render(request, "clinic/tutor_invalid.html", status=404)
    consent = get_object_or_404(Consentimiento.objects.select_related("mascota__tutor", "profesional"), pk=pk)
    error = ""
    if request.method == "POST":
        try:
            consent = tutor.sign_consent(
                consent, accept=request.POST.get("respuesta") == "autorizar",
                name=request.POST.get("nombre", ""), rut=request.POST.get("rut", ""),
                signature=request.POST.get("firma", ""), ip=request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR"),
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)
    return render(request, "clinic/tutor_consent.html", {"consent": consent, "error": error})
