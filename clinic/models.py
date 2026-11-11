from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Tutor(models.Model):
    nombre = models.CharField(max_length=150)
    email = models.EmailField("Correo electrónico")
    telefono = models.CharField("Teléfono", max_length=25)
    direccion = models.CharField("Dirección", max_length=200, blank=True)

    class Meta:
        ordering = ["nombre", "pk"]

    def __str__(self):
        return self.nombre


class Mascota(models.Model):
    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name="mascotas")
    nombre = models.CharField(max_length=100)
    especie = models.CharField(max_length=50)
    raza = models.CharField(max_length=80, blank=True)
    nacimiento = models.DateField("Fecha de nacimiento", null=True, blank=True)

    class Meta:
        ordering = ["nombre", "pk"]

    def __str__(self):
        return f"{self.nombre} · {self.tutor}"


class Profesional(models.Model):
    nombre = models.CharField(max_length=150)
    especialidad = models.CharField(max_length=100)

    class Meta:
        ordering = ["nombre", "pk"]
        verbose_name_plural = "profesionales"

    def __str__(self):
        return self.nombre


class Disponibilidad(models.Model):
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()

    class Meta:
        ordering = ["inicio", "pk"]
        verbose_name_plural = "bloques de disponibilidad"
        constraints = [
            models.CheckConstraint(condition=models.Q(fin__gt=models.F("inicio")),
                                   name="disponibilidad_rango_valido"),
        ]

    def __str__(self):
        return f"{self.profesional} · {timezone.localtime(self.inicio):%d/%m/%Y %H:%M}"


class Cita(models.Model):
    class Estado(models.TextChoices):
        AGENDADA = "agendada", "Agendada"
        ATENDIDA = "atendida", "Atendida"
        CANCELADA = "cancelada", "Cancelada"

    mascota = models.ForeignKey(Mascota, on_delete=models.PROTECT, related_name="citas")
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=200)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.AGENDADA)

    class Meta:
        ordering = ["inicio", "pk"]
        indexes = [models.Index(fields=["profesional", "inicio"]),
                   models.Index(fields=["mascota", "inicio"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(fin__gt=models.F("inicio")),
                                   name="cita_rango_valido"),
        ]

    def __str__(self):
        return f"{self.mascota.nombre} · {timezone.localtime(self.inicio):%d/%m/%Y %H:%M}"


class Atencion(models.Model):
    mascota = models.ForeignKey(Mascota, on_delete=models.PROTECT, related_name="atenciones")
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT)
    fecha = models.DateField(default=timezone.localdate)
    diagnostico = models.TextField("Diagnóstico")
    tratamiento = models.TextField(blank=True)
    receta = models.TextField("Receta médica", blank=True)
    examenes = models.TextField("Exámenes", blank=True)

    class Meta:
        ordering = ["-fecha", "-pk"]
        verbose_name = "atención"
        verbose_name_plural = "atenciones"

    def __str__(self):
        return f"{self.mascota.nombre} · {self.fecha:%d/%m/%Y}"


class Recordatorio(models.Model):
    class Tipo(models.TextChoices):
        VACUNA = "vacuna", "Vacunación"
        CONTROL = "control", "Control periódico"

    mascota = models.ForeignKey(Mascota, on_delete=models.PROTECT)
    tipo = models.CharField(max_length=10, choices=Tipo)
    detalle = models.CharField(max_length=160)
    fecha_objetivo = models.DateField("Fecha de vacuna o control")
    anticipacion_dias = models.PositiveSmallIntegerField("Días de anticipación", default=3)
    repetir_dias = models.PositiveSmallIntegerField("Repetir cada (días)", default=0,
                                                    help_text="Usa 0 para un aviso único.")
    enviar_el = models.DateField(editable=False, db_index=True)
    enviado_en = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["enviar_el", "pk"]

    def __str__(self):
        return f"{self.mascota.nombre} · {self.get_tipo_display()}"


class Insumo(models.Model):
    codigo = models.CharField("Código", max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.CharField("Categoría", max_length=80)
    unidad = models.CharField(max_length=40, default="unidad")
    minimo = models.PositiveIntegerField("Stock mínimo", default=0)
    stock = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["nombre", "pk"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Movimiento(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida"

    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=Tipo)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    motivo = models.CharField(max_length=200)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-registrado_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0),
                                   name="movimiento_cantidad_positiva"),
        ]
