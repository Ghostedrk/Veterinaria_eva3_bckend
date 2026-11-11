from django.conf import settings
from decimal import Decimal

from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
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
    activo = models.BooleanField(default=True, db_index=True,
                                 help_text="Un profesional inactivo conserva su historial, pero no recibe citas nuevas.")

    class Meta:
        ordering = ["-activo", "nombre", "pk"]
        verbose_name_plural = "profesionales"

    def __str__(self):
        return self.nombre if self.activo else f"{self.nombre} (inactivo)"


class Servicio(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    precio = models.PositiveIntegerField("Precio (CLP)")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["-activo", "nombre"]

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
        NO_ASISTIO = "no_asistio", "No asistió"

    class Respuesta(models.TextChoices):
        SIN_RESPUESTA = "", "Sin respuesta"
        CONFIRMADA = "confirmada", "Confirmada por el tutor"
        CANCELADA = "cancelada", "Cancelada por el tutor"

    mascota = models.ForeignKey(Mascota, on_delete=models.PROTECT, related_name="citas")
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=200)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.AGENDADA)
    respuesta_tutor = models.CharField("Respuesta del tutor", max_length=10, choices=Respuesta,
                                       blank=True, default="", editable=False)
    respondida_en = models.DateTimeField(null=True, blank=True, editable=False)
    aviso_enviado_en = models.DateTimeField("Aviso al tutor enviado", null=True, blank=True, editable=False)

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
    servicio = models.ForeignKey(Servicio, on_delete=models.PROTECT, null=True, blank=True, related_name="atenciones")
    monto = models.PositiveIntegerField("Monto cobrado (CLP)", null=True, blank=True,
                                        help_text="Si lo dejas vacío se usa el precio del servicio.")
    peso_kg = models.DecimalField("Peso (kg)", max_digits=5, decimal_places=2, null=True, blank=True,
                                  validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("150"))])

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


class OrdenCompra(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        PENDIENTE = "pendiente", "Esperando pago"
        PAGADA = "pagada", "Pagada"
        RECHAZADA = "rechazada", "Pago no realizado"
        ANULADA = "anulada", "Anulada"

    proveedor = models.CharField(max_length=150)
    observacion = models.CharField("Observación", max_length=200, blank=True)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.BORRADOR, db_index=True)
    total = models.PositiveIntegerField("Total (CLP)", default=0, editable=False)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
                                   editable=False)
    creada_en = models.DateTimeField(auto_now_add=True)
    pagada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
                                   null=True, blank=True, editable=False)
    pagada_en = models.DateTimeField(null=True, blank=True, editable=False)
    orden_webpay = models.CharField("Orden en Webpay", max_length=26, null=True, blank=True, unique=True,
                                    editable=False)
    token_webpay = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)
    codigo_autorizacion = models.CharField("Código de autorización", max_length=20, blank=True, editable=False)
    tarjeta = models.CharField("Tarjeta (últimos 4)", max_length=4, blank=True, editable=False)
    detalle_pago = models.CharField("Detalle del pago", max_length=200, blank=True, editable=False)

    class Meta:
        ordering = ["-creada_en", "-pk"]
        verbose_name = "orden de compra"
        verbose_name_plural = "órdenes de compra"

    def __str__(self):
        return f"{self.numero} · {self.proveedor}"

    @property
    def numero(self):
        return f"OC-{self.pk:05d}" if self.pk else "OC nueva"

    @property
    def editable(self):
        return self.estado in (self.Estado.BORRADOR, self.Estado.RECHAZADA)


class ItemOrden(models.Model):
    orden = models.ForeignKey(OrdenCompra, on_delete=models.CASCADE, related_name="items")
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, related_name="+")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    precio_unitario = models.PositiveIntegerField("Precio unitario (CLP)", validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = "ítem de la orden"
        verbose_name_plural = "ítems de la orden"
        constraints = [
            models.UniqueConstraint(fields=["orden", "insumo"], name="item_orden_insumo_unico"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0) & models.Q(precio_unitario__gt=0),
                                   name="item_orden_valores_positivos"),
        ]

    def __str__(self):
        return f"{self.insumo} × {self.cantidad}"

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario


def adjunto_path(instance, filename):
    return f"adjuntos/{timezone.now():%Y/%m}/{filename}"


class Adjunto(models.Model):
    class Tipo(models.TextChoices):
        RADIOGRAFIA = "radiografia", "Radiografía"
        ECOGRAFIA = "ecografia", "Ecografía"
        LABORATORIO = "laboratorio", "Examen de laboratorio"
        OTRO = "otro", "Otro"

    atencion = models.ForeignKey(Atencion, on_delete=models.CASCADE, related_name="adjuntos")
    tipo = models.CharField(max_length=12, choices=Tipo, default=Tipo.LABORATORIO)
    descripcion = models.CharField("Descripción", max_length=150, blank=True)
    archivo = models.FileField(upload_to=adjunto_path, validators=[
        FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"])])
    nombre_original = models.CharField(max_length=150, editable=False)
    tamano = models.PositiveIntegerField(default=0, editable=False)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
                                   editable=False)
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-subido_en", "-pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.nombre_original}"

    @property
    def es_imagen(self):
        return self.nombre_original.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "webp"}


class Consentimiento(models.Model):
    class Procedimiento(models.TextChoices):
        CIRUGIA = "cirugia", "Procedimiento quirúrgico"
        ANESTESIA = "anestesia", "Anestesia o sedación"
        EUTANASIA = "eutanasia", "Eutanasia"
        OTRO = "otro", "Otro procedimiento"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de firma"
        AUTORIZADO = "autorizado", "Autorizado"
        RECHAZADO = "rechazado", "Rechazado"

    mascota = models.ForeignKey(Mascota, on_delete=models.PROTECT, related_name="consentimientos")
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT)
    procedimiento = models.CharField(max_length=10, choices=Procedimiento)
    descripcion = models.TextField("Descripción del procedimiento")
    riesgos = models.TextField("Riesgos informados")
    fecha_procedimiento = models.DateField("Fecha del procedimiento")
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.PENDIENTE, editable=False)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
                                   editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    firmante_nombre = models.CharField("Nombre del firmante", max_length=150, blank=True, editable=False)
    firmante_rut = models.CharField("RUT del firmante", max_length=12, blank=True, editable=False)
    firma = models.TextField(blank=True, editable=False)  # PNG en data URL
    respondido_en = models.DateTimeField(null=True, blank=True, editable=False)
    ip_firma = models.GenericIPAddressField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-creado_en", "-pk"]

    def __str__(self):
        return f"{self.get_procedimiento_display()} · {self.mascota.nombre}"
