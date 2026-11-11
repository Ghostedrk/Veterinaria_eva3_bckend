from dataclasses import dataclass

from django.db.models import Q
from django.forms import DateInput, DateTimeInput, ModelForm, modelform_factory

from . import models


class ActiveProfessionalForm(ModelForm):
    """Only active professionals and services are offered; an existing record keeps its current one."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, model in (("profesional", models.Profesional), ("servicio", models.Servicio)):
            field = self.fields.get(name)
            if field is not None:
                current = getattr(self.instance, f"{name}_id", None)
                field.queryset = model.objects.filter(Q(activo=True) | Q(pk=current))


@dataclass(frozen=True)
class Resource:
    model: type
    title: str
    fields: tuple
    columns: tuple
    search: tuple
    related: tuple = ()
    append_only: bool = False
    soft_delete: bool = False  # Se desactiva en lugar de eliminarse.

    def queryset(self):
        return self.model.objects.select_related(*self.related) if self.related else self.model.objects.all()

    def form_class(self):
        widgets = {}
        for name in self.fields:
            field = self.model._meta.get_field(name)
            if field.get_internal_type() == "DateTimeField":
                widgets[name] = DateTimeInput(
                    format="%Y-%m-%dT%H:%M:%S", attrs={"type": "datetime-local", "step": "1"},
                )
            elif field.get_internal_type() == "DateField":
                widgets[name] = DateInput(format="%Y-%m-%d", attrs={"type": "date"})
        return modelform_factory(self.model, form=ActiveProfessionalForm, fields=self.fields, widgets=widgets)


RESOURCES = {
    "tutores": Resource(models.Tutor, "Tutores",
        ("nombre", "email", "telefono", "direccion"), ("nombre", "email", "telefono"),
        ("nombre", "email", "telefono")),
    "mascotas": Resource(models.Mascota, "Mascotas",
        ("tutor", "nombre", "especie", "raza", "nacimiento"), ("nombre", "especie", "raza", "tutor"),
        ("nombre", "especie", "tutor__nombre"), ("tutor",)),
    "profesionales": Resource(models.Profesional, "Profesionales",
        ("nombre", "especialidad"), ("nombre", "especialidad", "activo"), ("nombre", "especialidad"),
        soft_delete=True),
    "disponibilidad": Resource(models.Disponibilidad, "Disponibilidad",
        ("profesional", "inicio", "fin"), ("profesional", "inicio", "fin"),
        ("profesional__nombre",), ("profesional",)),
    "citas": Resource(models.Cita, "Citas",
        ("mascota", "profesional", "inicio", "fin", "motivo", "estado"),
        ("inicio", "fin", "mascota", "profesional", "estado", "respuesta_tutor"),
        ("mascota__nombre", "profesional__nombre", "motivo"), ("mascota__tutor", "profesional")),
    "atenciones": Resource(models.Atencion, "Atenciones clínicas",
        ("mascota", "profesional", "fecha", "servicio", "monto", "peso_kg", "diagnostico", "tratamiento",
         "receta", "examenes"),
        ("fecha", "mascota", "profesional", "servicio", "diagnostico"),
        ("mascota__nombre", "profesional__nombre", "diagnostico", "servicio__nombre"),
        ("mascota__tutor", "profesional", "servicio")),
    "servicios": Resource(models.Servicio, "Servicios y precios",
        ("nombre", "precio", "activo"), ("nombre", "precio", "activo"), ("nombre",)),
    "recordatorios": Resource(models.Recordatorio, "Recordatorios",
        ("mascota", "tipo", "detalle", "fecha_objetivo", "anticipacion_dias", "repetir_dias"),
        ("enviar_el", "mascota", "tipo", "detalle", "enviado_en"),
        ("mascota__nombre", "detalle"), ("mascota__tutor",)),
    "insumos": Resource(models.Insumo, "Insumos",
        ("codigo", "nombre", "categoria", "unidad", "minimo"),
        ("codigo", "nombre", "categoria", "stock", "minimo"),
        ("nombre", "codigo", "categoria")),
    "movimientos": Resource(models.Movimiento, "Movimientos de inventario",
        ("insumo", "tipo", "cantidad", "motivo"),
        ("registrado_en", "insumo", "tipo", "cantidad", "motivo", "registrado_por"),
        ("insumo__nombre", "insumo__codigo", "motivo"), ("insumo", "registrado_por"), True),
}


def is_readonly(resource, obj):
    return resource.append_only or bool(getattr(obj, "enviado_en", None))

