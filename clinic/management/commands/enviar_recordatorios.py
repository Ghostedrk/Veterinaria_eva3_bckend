from datetime import timedelta
from time import sleep

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clinic.models import Recordatorio
from clinic.services import reminder_send_date


class Command(BaseCommand):
    help = "Procesa los recordatorios pendientes de vacunación y controles."

    def add_arguments(self, parser):
        parser.add_argument("--cada", type=int, default=0,
                            help="Repite el procesamiento cada N segundos (mínimo 10).")

    def handle(self, *args, **options):
        interval = options["cada"]
        if interval and interval < 10:
            raise CommandError("Usa un intervalo de al menos 10 segundos.")
        try:
            while True:
                failures = self.process_pending()
                if not interval:
                    if failures:
                        raise CommandError(f"No se pudieron enviar {failures} avisos.")
                    return
                sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Procesamiento detenido.")

    def process_pending(self):
        today = timezone.localdate()
        pending = list(Recordatorio.objects.filter(
            enviar_el__lte=today, enviado_en__isnull=True,
        ).values_list("pk", flat=True))
        failures = 0
        for pk in pending:
            try:
                self.send_reminder(pk, today)
            except (OSError, RuntimeError) as exc:
                failures += 1
                self.stderr.write(f"Recordatorio {pk} pendiente ({type(exc).__name__}).")
        return failures

    @transaction.atomic
    def send_reminder(self, pk, today):
        reminder = Recordatorio.objects.select_for_update().filter(
            pk=pk, enviar_el__lte=today, enviado_en__isnull=True,
        ).first()
        if reminder is None:
            return

        pet = reminder.mascota
        tutor = pet.tutor
        sent = send_mail(
            "Recordatorio de Veterinaria San Francisco",
            f"Hola, {tutor.nombre}.\n\n"
            f"Te recordamos {reminder.get_tipo_display().lower()} de {pet.nombre} "
            f"para el {reminder.fecha_objetivo:%d/%m/%Y}.\n"
            f"Detalle: {reminder.detalle}\n\nVeterinaria San Francisco",
            None,
            [tutor.email],
        )
        if sent != 1:
            raise RuntimeError("El transporte no aceptó el mensaje.")
        reminder.enviado_en = timezone.now()
        reminder.save(update_fields=["enviado_en"])
        if reminder.repetir_dias:
            # Skip missed cycles when the service was offline instead of
            # sending several historical notices at once.
            elapsed = (today - reminder.enviar_el).days
            cycles = elapsed // reminder.repetir_dias + 1
            try:
                next_date = reminder.fecha_objetivo + timedelta(days=cycles * reminder.repetir_dias)
            except OverflowError:
                self.stderr.write(f"Recordatorio {pk} enviado; se alcanzó el límite de fechas.")
            else:
                Recordatorio.objects.create(
                    mascota=pet, tipo=reminder.tipo, detalle=reminder.detalle,
                    fecha_objetivo=next_date, anticipacion_dias=reminder.anticipacion_dias,
                    repetir_dias=reminder.repetir_dias,
                    enviar_el=reminder_send_date(next_date, reminder.anticipacion_dias),
                )
        self.stdout.write(f"Recordatorio {pk} procesado.")

