from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clinic.models import (Atencion, Cita, Disponibilidad, Insumo, Mascota, Movimiento, Profesional,
                           Recordatorio, Servicio, Tutor)
from clinic.services import save_record

# Correos en el dominio reservado example.test: los recordatorios nunca llegan a personas reales.
TUTORES = [
    ("Ana Pérez Muñoz", "ana.perez@example.test", "+56 9 5555 0101", "Av. Los Leones 123"),
    ("Luis Soto Rojas", "luis.soto@example.test", "+56 9 5555 0102", "Pasaje Las Rosas 45"),
    ("María José Fuentes", "mjose.fuentes@example.test", "+56 9 5555 0103", "Calle Prat 890"),
    ("Diego Herrera Silva", "diego.herrera@example.test", "+56 9 5555 0104", "Av. Brasil 2210"),
    ("Valentina Castro", "valentina.castro@example.test", "+56 9 5555 0105", ""),
]
MASCOTAS = [  # (tutor, nombre, especie, raza, años)
    (0, "Nube", "Gato", "Mestizo", 3), (0, "Rocco", "Perro", "Labrador", 6),
    (1, "Toby", "Perro", "Beagle", 2), (1, "Luna", "Perro", "Quiltro", 8),
    (2, "Michi", "Gato", "Siamés", 1), (3, "Kiara", "Perro", "Pastor alemán", 4),
    (3, "Pelusa", "Conejo", "Cabeza de león", 2), (4, "Simón", "Gato", "Persa", 5),
]
PROFESIONALES = [
    ("Dra. Camila Rojas", "Medicina general"),
    ("Dr. Tomás Vera", "Cirugía"),
    ("Dra. Francisca Lagos", "Dermatología"),
]
MOTIVOS = ["Control general", "Vacuna antirrábica", "Vacuna séxtuple", "Revisión de piel",
           "Control post operatorio", "Desparasitación", "Curación de herida", "Control dental"]
ATENCIONES = [  # (mascota, profesional, días atrás, diagnóstico, tratamiento, receta, exámenes)
    (0, 0, 20, "Gingivitis leve", "Limpieza dental y control en 30 días",
     "Clorhexidina gel 0,12 % cada 12 h por 7 días", ""),
    (0, 1, 120, "Esterilización sin complicaciones", "Reposo 10 días y collar isabelino",
     "Meloxicam 0,5 mg cada 24 h por 3 días", "Hemograma prequirúrgico normal"),
    (1, 0, 45, "Otitis externa en oído derecho", "Limpieza ótica diaria",
     "Gotas óticas de otomax, 5 gotas cada 12 h por 10 días", "Citología ótica"),
    (3, 2, 15, "Dermatitis alérgica", "Cambio de alimento a dieta hipoalergénica",
     "Apoquel 16 mg cada 12 h por 14 días", "Raspado cutáneo negativo"),
    (5, 1, 60, "Fractura de falange resuelta", "Retiro de vendaje y fisioterapia", "",
     "Radiografía de control"),
    (7, 0, 5, "Bola de pelo", "Malta y cepillado diario", "Pasta de malta 5 cm al día", ""),
]
INSUMOS = [  # (código, nombre, categoría, unidad, mínimo, entrada inicial, salida)
    ("VAC-RAB", "Vacuna antirrábica", "Biológicos", "dosis", 10, 30, 8),
    ("VAC-SEX", "Vacuna séxtuple canina", "Biológicos", "dosis", 10, 12, 5),
    ("VAC-TRI", "Vacuna triple felina", "Biológicos", "dosis", 8, 15, 4),
    ("GUA-NIT", "Guantes de nitrilo", "Protección", "caja", 5, 6, 2),
    ("JER-3ML", "Jeringa desechable 3 ml", "Insumos clínicos", "unidad", 50, 200, 35),
    ("ANT-PAR", "Antiparasitario interno", "Fármacos", "comprimido", 20, 40, 12),
]


SERVICIOS = [
    ("Consulta general", 18000), ("Vacunación", 15000), ("Control post operatorio", 12000),
    ("Dermatología", 25000), ("Cirugía menor", 85000), ("Limpieza dental", 45000), ("Radiografía", 30000),
]
# Palabras del diagnóstico que indican qué servicio corresponde a una atención existente.
KEYWORDS = [("dental", "Limpieza dental"), ("gingiv", "Limpieza dental"), ("esteriliz", "Cirugía menor"),
            ("fractura", "Radiografía"), ("dermat", "Dermatología"), ("otitis", "Consulta general")]
# Historial de peso mensual (kg) para que se vea la curva de crecimiento.
PESOS = {0: [3.1, 3.4, 3.8, 4.0, 4.1, 4.2], 2: [7.5, 8.6, 9.8, 10.9, 11.6, 12.1], 5: [27.0, 28.1, 29.4, 30.0, 30.6, 31.2]}


class Command(BaseCommand):
    help = ("Carga datos de ejemplo para la demostración. Si la base ya tiene datos, solo agrega lo que falta "
            "(servicios, montos, pesos e historial) sin duplicar registros.")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        if user is None:
            raise CommandError("Primero crea la cuenta de Jefatura con createsuperuser.")
        if Tutor.objects.exists():
            if Servicio.objects.exists():
                self.stdout.write("La base ya tiene datos de demostración completos. No se cargó nada.")
                return
            with transaction.atomic():
                self.complement(user)
            self.stdout.write(self.style.SUCCESS(
                f"Datos existentes completados: {Servicio.objects.count()} servicios, "
                f"{Atencion.objects.filter(monto__isnull=False).count()} atenciones con monto y "
                f"{Atencion.objects.filter(peso_kg__isnull=False).count()} registros de peso."
            ))
            return
        with transaction.atomic():
            self.load(user)
            self.complement(user)
        self.stdout.write(self.style.SUCCESS(
            f"Datos de demostración cargados: {Tutor.objects.count()} tutores, "
            f"{Mascota.objects.count()} mascotas, {Cita.objects.count()} citas, "
            f"{Atencion.objects.count()} atenciones, {Recordatorio.objects.count()} recordatorios "
            f"y {Insumo.objects.count()} insumos."
        ))

    def load(self, user):
        today = timezone.localdate()
        now = timezone.now()
        tutores = [Tutor.objects.create(nombre=n, email=e, telefono=t, direccion=d) for n, e, t, d in TUTORES]
        mascotas = [
            save_record(Mascota(tutor=tutores[t], nombre=n, especie=e, raza=r,
                                nacimiento=today - timedelta(days=365 * age + 40)), user=user)
            for t, n, e, r, age in MASCOTAS
        ]
        vets = [Profesional.objects.create(nombre=n, especialidad=e) for n, e in PROFESIONALES]

        def at(day, hour, minute=0):
            return timezone.make_aware(datetime.combine(day, time(hour, minute)))

        # Disponibilidad de lunes a viernes, esta semana y la siguiente, mañana y tarde.
        monday = today - timedelta(days=today.weekday())
        workdays = [monday + timedelta(days=d) for d in range(14) if (monday + timedelta(days=d)).weekday() < 5]
        for day in workdays:
            for vet in vets:
                for start, end in ((9, 13), (14, 18)):
                    save_record(Disponibilidad(profesional=vet, inicio=at(day, start), fin=at(day, end)), user=user)

        # Tres citas por día hábil, repartidas entre profesionales y mascotas.
        slots = [(9, 30), (11, 0), (15, 0), (16, 30)]
        n = 0
        for d, day in enumerate(workdays):
            for i, vet in enumerate(vets):
                hour, minute = slots[(d + i) % len(slots)]
                start = at(day, hour, minute)
                cita = Cita(mascota=mascotas[n % len(mascotas)], profesional=vet,
                            inicio=start, fin=start + timedelta(minutes=30), motivo=MOTIVOS[n % len(MOTIVOS)])
                if cita.fin < now:
                    cita.estado = Cita.Estado.ATENDIDA
                save_record(cita, user=user)
                n += 1

        for m, v, days_ago, diag, trat, receta, examenes in ATENCIONES:
            save_record(Atencion(mascota=mascotas[m], profesional=vets[v], fecha=today - timedelta(days=days_ago),
                                 diagnostico=diag, tratamiento=trat, receta=receta, examenes=examenes), user=user)

        # Recordatorios: dos quedan listos para enviarse hoy y el resto programados.
        for m, tipo, detalle, days, lead, repeat in (
            (0, "vacuna", "Vacuna triple felina anual", 2, 3, 365),
            (2, "vacuna", "Segunda dosis séxtuple", 1, 2, 0),
            (3, "control", "Control de dermatitis", 10, 3, 0),
            (5, "control", "Control traumatológico", 20, 5, 0),
            (1, "control", "Control de otitis", 30, 3, 0),
            (6, "vacuna", "Vacuna contra mixomatosis", 45, 7, 180),
        ):
            save_record(Recordatorio(mascota=mascotas[m], tipo=tipo, detalle=detalle,
                                     fecha_objetivo=today + timedelta(days=days),
                                     anticipacion_dias=lead, repetir_dias=repeat), user=user)

        # Inventario con historial; dos insumos quedan en el stock mínimo para la alerta del inicio.
        for code, name, category, unit, minimum, entry, used in INSUMOS:
            item = Insumo.objects.create(codigo=code, nombre=name, categoria=category, unidad=unit, minimo=minimum)
            save_record(Movimiento(insumo=item, tipo="entrada", cantidad=entry, motivo="Compra a proveedor"), user=user)
            save_record(Movimiento(insumo=item, tipo="salida", cantidad=used, motivo="Uso en atenciones"), user=user)

    def complement(self, user):
        """Servicios con precio, cobros, pesos e inasistencias para el dashboard y las curvas."""
        today = timezone.localdate()
        services = {name: Servicio.objects.get_or_create(nombre=name, defaults={"precio": price})[0]
                    for name, price in SERVICIOS}
        for visit in Atencion.objects.filter(servicio__isnull=True):
            text = visit.diagnostico.lower()
            name = next((service for word, service in KEYWORDS if word in text), "Consulta general")
            Atencion.objects.filter(pk=visit.pk).update(servicio=services[name], monto=services[name].precio)

        pets = list(Mascota.objects.order_by("pk"))
        vets = list(Profesional.objects.filter(activo=True).order_by("pk")) or list(Profesional.objects.all())
        for index, weights in PESOS.items():
            if index >= len(pets) or not vets:
                continue
            for months_ago, weight in zip(range(len(weights) - 1, -1, -1), weights):
                day = today - timedelta(days=30 * months_ago + 3)
                service = services["Vacunación" if months_ago % 2 else "Consulta general"]
                save_record(Atencion(mascota=pets[index], profesional=vets[months_ago % len(vets)], fecha=day,
                                     servicio=service, peso_kg=Decimal(str(weight)),
                                     diagnostico="Control de rutina: peso y condición corporal adecuados.",
                                     tratamiento="Mantener alimentación y actividad."), user=user)

        # Algunas citas pasadas quedan como inasistencia para la tasa de no-show.
        past = Cita.objects.filter(estado=Cita.Estado.ATENDIDA, fin__lt=timezone.now()).order_by("pk")
        for cita in past[::5]:
            Cita.objects.filter(pk=cita.pk).update(estado=Cita.Estado.NO_ASISTIO)
