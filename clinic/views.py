from datetime import date, datetime, time, timedelta
from functools import wraps

from django.contrib import messages
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .models import Cita, Disponibilidad, Insumo, Mascota, Profesional, Recordatorio, Tutor
from . import roles
from .resources import RESOURCES, is_readonly
from .services import delete_record, save_record, set_professional_active

User = get_user_model()
PROTECTED_MESSAGE = "Hay registros vinculados a este elemento. Revisa esas relaciones antes de eliminarlo."
CONFLICT_MESSAGE = "Otro cambio entró en conflicto con esta operación. Recarga la página y vuelve a intentar."


def staff_required(view):
    @never_cache
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def full_staff_required(view):
    """Jefatura y Administración; Recepción recibe 403."""
    @staff_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not roles.is_full_staff(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def check_can_edit(request, slug):
    if slug in roles.READ_ONLY_FOR_RECEPTION and not roles.is_full_staff(request.user):
        raise PermissionDenied


def resource_for(slug):
    try:
        return RESOURCES[slug]
    except KeyError as exc:
        raise Http404 from exc


def field_label(model, name):
    return model._meta.get_field(name).verbose_name.capitalize()


def field_value(obj, name):
    display = getattr(obj, f"get_{name}_display", None)
    value = display() if display else getattr(obj, name)
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return value


@staff_required
@require_safe
def dashboard(request):
    today = timezone.localdate()
    appointments = RESOURCES["citas"].queryset().filter(
        inicio__date=today, estado=Cita.Estado.AGENDADA,
    )
    reminders = RESOURCES["recordatorios"].queryset().filter(
        enviar_el__lte=today, enviado_en__isnull=True,
    )
    low_stock = Insumo.objects.filter(stock__lte=F("minimo"))
    return render(request, "clinic/dashboard.html", {
        "today": today, "now": timezone.now(),
        "appointments": appointments[:8], "appointment_count": appointments.count(),
        "reminder_count": reminders.count(), "low_stock": low_stock[:6],
        "stock_count": low_stock.count(), "pet_count": Mascota.objects.count(),
    })


@staff_required
@require_safe
def calendar(request):
    try:
        selected = date.fromisoformat(request.GET.get("fecha", ""))
        if not 1900 <= selected.year <= 9998:
            raise ValueError
    except ValueError:
        selected = timezone.localdate()

    start = selected - timedelta(days=selected.weekday())
    end = start + timedelta(days=7)
    first = timezone.make_aware(datetime.combine(start, time.min))
    last = timezone.make_aware(datetime.combine(end, time.min))
    appointments = RESOURCES["citas"].queryset().filter(inicio__lt=last, fin__gt=first)
    windows = RESOURCES["disponibilidad"].queryset().filter(inicio__lt=last, fin__gt=first)
    professionals = Profesional.objects.all()
    professional_id = request.GET.get("profesional", "")
    professional = professionals.filter(pk=professional_id).first() if (
        professional_id.isascii() and professional_id.isdigit() and len(professional_id) < 19
    ) else None
    if professional:
        appointments = appointments.filter(profesional=professional)
        windows = windows.filter(profesional=professional)

    appointments = list(appointments)
    windows = list(windows)
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        first_hour = timezone.make_aware(datetime.combine(day, time.min))
        last_hour = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
        days.append({
            "date": day,
            "appointments": [c for c in appointments if c.inicio < last_hour and c.fin > first_hour],
            "windows": [w for w in windows if w.inicio < last_hour and w.fin > first_hour],
        })
    return render(request, "clinic/calendar.html", {
        "days": days, "today": timezone.localdate(), "start": start, "end": end - timedelta(days=1),
        "previous": start - timedelta(days=7), "next_week": end,
        "professionals": professionals.filter(activo=True), "professional": professional,
    })


@staff_required
@require_safe
def record_list(request, slug):
    resource = resource_for(slug)
    items = resource.queryset()
    query = request.GET.get("q", "").strip()[:120]
    if query:
        matching = Q()
        for field in resource.search:
            matching |= Q(**{f"{field}__icontains": query})
        items = items.filter(matching)
    page = Paginator(items, 20).get_page(request.GET.get("page"))
    return render(request, "clinic/list.html", {
        "resource": resource, "slug": slug, "query": query, "page": page,
        "headers": [field_label(resource.model, field) for field in resource.columns],
        "rows": [(obj, [field_value(obj, name) for name in resource.columns]) for obj in page],
    })


@staff_required
@require_safe
def record_detail(request, slug, pk):
    resource = resource_for(slug)
    obj = get_object_or_404(resource.queryset(), pk=pk)
    names = dict.fromkeys((*resource.fields, *resource.columns))
    return render(request, "clinic/detail.html", {
        "resource": resource, "slug": slug, "object": obj,
        "readonly": is_readonly(resource, obj),
        "can_edit": slug not in roles.READ_ONLY_FOR_RECEPTION or roles.is_full_staff(request.user),
        "fields": [(field_label(resource.model, name), field_value(obj, name)) for name in names],
        "pets": obj.mascotas.all() if isinstance(obj, Tutor) else None,
        "pet_profile": isinstance(obj, Mascota),
        "visits": obj.atenciones.select_related("profesional") if isinstance(obj, Mascota) else None,
    })


@staff_required
@require_http_methods(["GET", "HEAD", "POST"])
def record_form(request, slug, pk=None):
    resource = resource_for(slug)
    check_can_edit(request, slug)
    obj = get_object_or_404(resource.queryset(), pk=pk) if pk is not None else None
    if obj is not None and is_readonly(resource, obj):
        raise PermissionDenied
    form_class = resource.form_class()
    if request.method == "POST":
        form = form_class(request.POST, instance=obj)
        if form.is_valid():
            try:
                record = save_record(form.save(commit=False), user=request.user)
            except ValidationError as exc:
                if hasattr(exc, "error_dict"):
                    for field, errors in exc.error_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, exc)
            except IntegrityError:
                form.add_error(None, CONFLICT_MESSAGE)
            except resource.model.DoesNotExist as exc:
                raise Http404 from exc
            else:
                messages.success(request, "Cambios guardados.")
                return redirect("record-detail", slug=slug, pk=record.pk)
    else:
        initial = {key: request.GET[key] for key in ("mascota", "insumo", "profesional")
                   if key in request.GET and key in form_class.base_fields}
        form = form_class(instance=obj, initial=initial if obj is None else None)
    return render(request, "clinic/form.html", {
        "form": form, "title": f"{'Editar' if obj else 'Crear'} {resource.model._meta.verbose_name}",
        "slug": slug, "object": obj,
    })


@staff_required
@require_http_methods(["GET", "HEAD", "POST"])
def record_delete(request, slug, pk):
    resource = resource_for(slug)
    check_can_edit(request, slug)
    obj = get_object_or_404(resource.queryset(), pk=pk)
    if resource.soft_delete:
        messages.info(request, "Este registro no se elimina: desactívalo para conservar su historial.")
        return redirect("record-detail", slug=slug, pk=pk)
    if is_readonly(resource, obj):
        raise PermissionDenied
    if request.method == "POST":
        try:
            delete_record(obj)
        except ProtectedError:
            messages.error(request, PROTECTED_MESSAGE)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        except IntegrityError:
            messages.error(request, CONFLICT_MESSAGE)
        except resource.model.DoesNotExist as exc:
            raise Http404 from exc
        else:
            messages.success(request, "Registro eliminado.")
            return redirect("record-list", slug=slug)
        return redirect("record-detail", slug=slug, pk=pk)
    return render(request, "clinic/delete.html", {"object": obj, "slug": slug})


class AccountForm(UserCreationForm):
    rol = forms.ChoiceField(choices=roles.ROLES, initial="administracion",
                            help_text="Recepción no gestiona profesionales, no hace compras ni entra a Django Admin.")


def apply_role(account, role):
    group, _ = Group.objects.get_or_create(name=roles.RECEPCION)
    if role == "recepcion":
        account.groups.add(group)
    else:
        account.groups.remove(group)


@staff_required
@require_http_methods(["GET", "HEAD", "POST"])
def accounts(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = AccountForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            account = form.save(commit=False)
            account.is_staff = True
            account.save()
            apply_role(account, form.cleaned_data["rol"])
        messages.success(request, f"Cuenta de {dict(roles.ROLES)[form.cleaned_data['rol']]} creada.")
        return redirect("accounts")
    team = User.objects.filter(is_staff=True).prefetch_related("groups").order_by("username")
    return render(request, "clinic/accounts.html", {
        "form": form,
        "accounts": [(account, roles.role_name(account)) for account in team],
    })


@staff_required
@require_POST
def account_status(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    account = get_object_or_404(User, is_staff=True, is_superuser=False, pk=pk)
    account.is_active = request.POST.get("activo") == "1"
    account.save(update_fields=["is_active"])
    messages.success(request, "Acceso actualizado.")
    return redirect("accounts")


@staff_required
@require_POST
def account_role(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied
    account = get_object_or_404(User, is_staff=True, is_superuser=False, pk=pk)
    role = request.POST.get("rol")
    if role not in dict(roles.ROLES):
        raise PermissionDenied
    apply_role(account, role)
    messages.success(request, f"{account.username} ahora tiene el rol {dict(roles.ROLES)[role]}.")
    return redirect("accounts")


@full_staff_required
@require_POST
def professional_status(request, pk):
    professional = get_object_or_404(Profesional, pk=pk)
    active = request.POST.get("activo") == "1"
    try:
        set_professional_active(professional, active, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"{professional.nombre} quedó {'activo' if active else 'inactivo'}.")
    return redirect("record-detail", slug="profesionales", pk=pk)
