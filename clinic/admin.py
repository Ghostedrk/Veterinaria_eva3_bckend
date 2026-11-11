from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, F
from django.utils import timezone
from django.utils.html import format_html

from .models import (Atencion, Cita, Disponibilidad, Insumo, ItemOrden, Mascota, Movimiento, OrdenCompra,
                     Profesional, Recordatorio, Tutor)
from . import roles
from .services import (affected_appointments, delete_record, reminder_send_date, save_record,
                       set_professional_active, validate_rules)

admin.site.site_header = "Veterinaria San Francisco"
admin.site.site_title = "Administración PetCare"
admin.site.index_title = "Administración de la clínica"
# Recepción no entra a Django Admin: solo Jefatura y Administración.
admin.site.has_permission = lambda request: roles.is_full_staff(request.user)


def badge(text, tone):
    return format_html('<span class="pc-badge pc-{}">{}</span>', tone, text)


class RulesForm(forms.ModelForm):
    """Runs the same business rules as the panel and the API before saving."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("profesional")
        if field is not None:
            current = getattr(self.instance, "profesional_id", None)
            field.queryset = field.queryset.filter(models.Q(activo=True) | models.Q(pk=current))

    def _post_clean(self):
        super()._post_clean()
        if self._errors:
            return
        obj = self.instance
        try:
            if isinstance(obj, Recordatorio) and obj.fecha_objetivo is not None:
                obj.enviar_el = reminder_send_date(obj.fecha_objetivo, obj.anticipacion_dias)
            validate_rules(obj)
        except ValidationError as exc:
            self._update_errors(exc)


class ClinicAdmin(admin.ModelAdmin):
    """Clinic models follow the panel's roles: every active staff account manages them."""

    form = RulesForm
    list_per_page = 25

    @staticmethod
    def is_staff(request):
        return roles.is_full_staff(request.user)

    def has_module_permission(self, request):
        return self.is_staff(request)

    def has_view_permission(self, request, obj=None):
        return self.is_staff(request)

    def has_add_permission(self, request):
        return self.is_staff(request)

    def has_change_permission(self, request, obj=None):
        return self.is_staff(request)

    def has_delete_permission(self, request, obj=None):
        return self.is_staff(request)

    def save_model(self, request, obj, form, change):
        save_record(obj, user=request.user)

    def delete_model(self, request, obj):
        delete_record(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            try:
                delete_record(obj)
            except ValidationError as exc:
                self.message_user(request, f"{obj}: {' '.join(exc.messages)}", messages.WARNING)


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    show_change_link = True
    can_delete = False

    def get_readonly_fields(self, request, obj=None):
        return self.fields

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MascotaInline(ReadOnlyInline):
    model = Mascota
    fields = ("nombre", "especie", "raza", "nacimiento")


class AtencionInline(ReadOnlyInline):
    model = Atencion
    fields = ("fecha", "profesional", "diagnostico", "tratamiento")
    verbose_name_plural = "Ficha clínica (atenciones)"


class RecordatorioInline(ReadOnlyInline):
    model = Recordatorio
    fields = ("tipo", "detalle", "fecha_objetivo", "enviar_el", "enviado_en")


class MovimientoInline(ReadOnlyInline):
    model = Movimiento
    fields = ("registrado_en", "tipo", "cantidad", "motivo", "registrado_por")
    show_change_link = False


@admin.register(Tutor)
class TutorAdmin(ClinicAdmin):
    list_display = ("nombre", "email", "telefono", "total_mascotas")
    search_fields = ("nombre", "email", "telefono")
    inlines = [MascotaInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_mascotas=Count("mascotas"))

    @admin.display(description="Mascotas", ordering="n_mascotas")
    def total_mascotas(self, obj):
        return obj.n_mascotas


@admin.register(Mascota)
class MascotaAdmin(ClinicAdmin):
    list_display = ("nombre", "especie", "raza", "tutor", "edad")
    list_filter = ("especie",)
    search_fields = ("nombre", "raza", "tutor__nombre", "tutor__email")
    list_select_related = ("tutor",)
    autocomplete_fields = ("tutor",)
    inlines = [AtencionInline, RecordatorioInline]

    @admin.display(description="Edad", ordering="nacimiento")
    def edad(self, obj):
        if not obj.nacimiento:
            return "—"
        days = (timezone.localdate() - obj.nacimiento).days
        return f"{days // 365} años" if days >= 365 else f"{days // 30} meses"


@admin.register(Profesional)
class ProfesionalAdmin(ClinicAdmin):
    list_display = ("nombre", "especialidad", "estado")
    list_filter = ("activo", "especialidad")
    search_fields = ("nombre", "especialidad")
    readonly_fields = ("activo",)
    actions = ("desactivar", "reactivar")

    @admin.display(description="Estado", ordering="activo")
    def estado(self, obj):
        return badge("Activo", "ok") if obj.activo else badge("Inactivo", "muted")

    def get_search_results(self, request, queryset, search_term):
        # El autocompletado de citas, disponibilidad y atenciones ofrece solo activos.
        queryset, distinct = super().get_search_results(request, queryset, search_term)
        if request.path.endswith("/autocomplete/"):
            queryset = queryset.filter(activo=True)
        return queryset, distinct

    def has_delete_permission(self, request, obj=None):
        return False  # Se desactivan para conservar su historial.

    def change_active(self, request, queryset, active):
        for professional in queryset:
            try:
                set_professional_active(professional, active, user=request.user)
            except ValidationError as exc:
                self.message_user(request, " ".join(exc.messages), messages.WARNING)
            else:
                self.message_user(request, f"{professional.nombre} quedó {'activo' if active else 'inactivo'}.")

    @admin.action(description="Desactivar profesionales seleccionados")
    def desactivar(self, request, queryset):
        self.change_active(request, queryset, False)

    @admin.action(description="Reactivar profesionales seleccionados")
    def reactivar(self, request, queryset):
        self.change_active(request, queryset, True)


@admin.register(Disponibilidad)
class DisponibilidadAdmin(ClinicAdmin):
    list_display = ("profesional", "inicio", "fin", "duracion", "citas_agendadas")
    list_filter = ("profesional", ("inicio", admin.DateFieldListFilter))
    search_fields = ("profesional__nombre",)
    list_select_related = ("profesional",)
    autocomplete_fields = ("profesional",)
    date_hierarchy = "inicio"

    @admin.display(description="Duración")
    def duracion(self, obj):
        minutes = int((obj.fin - obj.inicio).total_seconds() // 60)
        return f"{minutes // 60} h {minutes % 60:02d} min"

    @admin.display(description="Citas agendadas")
    def citas_agendadas(self, obj):
        return affected_appointments(obj).count()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and affected_appointments(obj).exists():
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Cita)
class CitaAdmin(ClinicAdmin):
    list_display = ("inicio", "fin", "mascota", "tutor", "profesional", "motivo", "estado_badge")
    list_filter = ("estado", "profesional", ("inicio", admin.DateFieldListFilter))
    search_fields = ("mascota__nombre", "mascota__tutor__nombre", "profesional__nombre", "motivo")
    list_select_related = ("mascota__tutor", "profesional")
    autocomplete_fields = ("mascota", "profesional")
    date_hierarchy = "inicio"
    actions = ("marcar_atendida", "marcar_cancelada")

    @admin.display(description="Tutor", ordering="mascota__tutor__nombre")
    def tutor(self, obj):
        return obj.mascota.tutor

    @admin.display(description="Estado", ordering="estado")
    def estado_badge(self, obj):
        tone = {"agendada": "info", "atendida": "ok", "cancelada": "muted"}[obj.estado]
        return badge(obj.get_estado_display(), tone)

    def change_state(self, request, queryset, state):
        changed = 0
        for cita in queryset:
            cita.estado = state
            try:
                save_record(cita, user=request.user, changed_fields={"estado"})
            except ValidationError as exc:
                self.message_user(request, f"{cita}: {' '.join(exc.messages)}", messages.WARNING)
            else:
                changed += 1
        self.message_user(request, f"{changed} cita(s) actualizadas.", messages.SUCCESS)

    @admin.action(description="Marcar como atendidas")
    def marcar_atendida(self, request, queryset):
        self.change_state(request, queryset, Cita.Estado.ATENDIDA)

    @admin.action(description="Cancelar citas seleccionadas")
    def marcar_cancelada(self, request, queryset):
        self.change_state(request, queryset, Cita.Estado.CANCELADA)


@admin.register(Atencion)
class AtencionAdmin(ClinicAdmin):
    list_display = ("fecha", "mascota", "profesional", "resumen")
    list_filter = ("profesional", "fecha")
    search_fields = ("mascota__nombre", "mascota__tutor__nombre", "profesional__nombre", "diagnostico")
    list_select_related = ("mascota__tutor", "profesional")
    autocomplete_fields = ("mascota", "profesional")
    date_hierarchy = "fecha"
    fieldsets = (
        ("Paciente", {"fields": ("mascota", "profesional", "fecha")}),
        ("Ficha clínica", {"fields": ("diagnostico", "tratamiento", "receta", "examenes")}),
    )

    @admin.display(description="Diagnóstico")
    def resumen(self, obj):
        return obj.diagnostico if len(obj.diagnostico) <= 60 else f"{obj.diagnostico[:57]}…"


@admin.register(Recordatorio)
class RecordatorioAdmin(ClinicAdmin):
    list_display = ("mascota", "tipo", "detalle", "fecha_objetivo", "enviar_el", "estado")
    list_filter = ("tipo", ("enviado_en", admin.EmptyFieldListFilter), "enviar_el")
    search_fields = ("mascota__nombre", "mascota__tutor__nombre", "detalle")
    list_select_related = ("mascota",)
    autocomplete_fields = ("mascota",)
    readonly_fields = ("enviar_el", "enviado_en")
    date_hierarchy = "enviar_el"

    @admin.display(description="Estado")
    def estado(self, obj):
        if obj.enviado_en:
            return badge("Enviado", "ok")
        if obj.enviar_el <= timezone.localdate():
            return badge("Por enviar", "warn")
        return badge("Programado", "info")

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.enviado_en:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.enviado_en:
            return False
        return super().has_delete_permission(request, obj)


class StockFilter(admin.SimpleListFilter):
    title = "estado de stock"
    parameter_name = "stock"

    def lookups(self, request, model_admin):
        return (("bajo", "Igual o bajo el mínimo"), ("ok", "Sobre el mínimo"))

    def queryset(self, request, queryset):
        if self.value() == "bajo":
            return queryset.filter(stock__lte=F("minimo"))
        if self.value() == "ok":
            return queryset.filter(stock__gt=F("minimo"))
        return queryset


@admin.register(Insumo)
class InsumoAdmin(ClinicAdmin):
    list_display = ("codigo", "nombre", "categoria", "stock", "minimo", "unidad", "estado_stock")
    list_filter = (StockFilter, "categoria")
    search_fields = ("codigo", "nombre", "categoria")
    readonly_fields = ("stock",)
    inlines = [MovimientoInline]

    @admin.display(description="Stock")
    def estado_stock(self, obj):
        return badge("Reponer", "warn") if obj.stock <= obj.minimo else badge("OK", "ok")


@admin.register(Movimiento)
class MovimientoAdmin(ClinicAdmin):
    """Inventory ledger: entries can be added and read, never edited or deleted."""

    list_display = ("registrado_en", "insumo", "tipo", "cantidad", "motivo", "registrado_por")
    list_filter = ("tipo", "insumo", ("registrado_en", admin.DateFieldListFilter))
    search_fields = ("insumo__nombre", "insumo__codigo", "motivo")
    list_select_related = ("insumo", "registrado_por")
    autocomplete_fields = ("insumo",)
    fields = ("insumo", "tipo", "cantidad", "motivo")
    date_hierarchy = "registrado_en"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_fields(self, request, obj=None):
        if obj is not None:
            return (*self.fields, "registrado_por", "registrado_en")
        return self.fields

    def get_readonly_fields(self, request, obj=None):
        return ("registrado_por", "registrado_en") if obj is not None else ()


class ItemOrdenInline(ReadOnlyInline):
    model = ItemOrden
    fields = ("insumo", "cantidad", "precio_unitario")
    show_change_link = False


@admin.register(OrdenCompra)
class OrdenCompraAdmin(ClinicAdmin):
    """Read-only: orders are created and paid from the panel so payment always goes through Webpay."""

    list_display = ("numero", "proveedor", "total_clp", "estado_badge", "creada_en", "pagada_en", "tarjeta")
    list_filter = ("estado", ("creada_en", admin.DateFieldListFilter))
    search_fields = ("proveedor", "orden_webpay", "codigo_autorizacion")
    list_select_related = ("creada_por", "pagada_por")
    date_hierarchy = "creada_en"
    inlines = [ItemOrdenInline]
    fields = ("proveedor", "observacion", "estado", "total", "creada_por", "creada_en", "pagada_por",
              "pagada_en", "orden_webpay", "codigo_autorizacion", "tarjeta", "detalle_pago")
    readonly_fields = fields

    @admin.display(description="Orden", ordering="pk")
    def numero(self, obj):
        return obj.numero

    @admin.display(description="Total", ordering="total")
    def total_clp(self, obj):
        return f"${obj.total:,}".replace(",", ".")

    @admin.display(description="Estado", ordering="estado")
    def estado_badge(self, obj):
        tone = {"borrador": "info", "pendiente": "warn", "pagada": "ok", "rechazada": "warn", "anulada": "muted"}
        return badge(obj.get_estado_display(), tone[obj.estado])

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
