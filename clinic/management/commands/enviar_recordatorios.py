from datetime import timedelta
from time import sleep

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clinic.models import Cita, Recordatorio
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

    def process_appointments(self):
        """Avisa al tutor 24 horas antes de su cita, con el enlace para confirmar o cancelar."""
        from clinic import tutor

        now = timezone.now()
        pending = Cita.objects.filter(
            estado=Cita.Estado.AGENDADA, aviso_enviado_en__isnull=True, respuesta_tutor="",
            inicio__gt=now, inicio__lte=now + timedelta(hours=24),
        ).select_related("mascota__tutor", "profesional")
        failures = 0
        for cita in pending:
            url = tutor.appointment_url(cita)
            if not url:
                self.stderr.write("Configura PETCARE_SITE_URL para enviar los avisos de citas.")
                return 0
            try:
                tutor.send_appointment_link(cita, url)
            except (OSError, RuntimeError) as exc:
                failures += 1
                self.stderr.write(f"Aviso de cita {cita.pk} pendiente ({type(exc).__name__}).")
                continue
            Cita.objects.filter(pk=cita.pk).update(aviso_enviado_en=timezone.now())
            self.stdout.write(f"Aviso de cita {cita.pk} enviado.")
        return failures

    def process_pending(self):
        failures = self.process_appointments()
        return failures + self.process_reminders()

    def process_reminders(self):
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

