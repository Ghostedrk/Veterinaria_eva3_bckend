from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.db import models
from django.utils import timezone

from .models import Cita, Disponibilidad, Insumo, Mascota, Movimiento, Profesional, Recordatorio, Tutor
from .services import save_record


class ClinicFlows(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.staff = users.create_user("administracion", is_staff=True)
        cls.manager = users.create_user("jefatura", is_staff=True, is_superuser=True)
        cls.outsider = users.create_user("externo")
        cls.tutor = Tutor.objects.create(nombre="Ana Demo", email="ana@example.test", telefono="555000")
        cls.pet = Mascota.objects.create(tutor=cls.tutor, nombre="Nube", especie="Gato")
        cls.vet = Profesional.objects.create(nombre="Camila Demo", especialidad="Medicina general")

    def setUp(self):
        self.client.force_login(self.staff)
        self.start = timezone.localtime().replace(second=0, microsecond=0) + timedelta(days=1)
        self.window = Disponibilidad.objects.create(
            profesional=self.vet, inicio=self.start, fin=self.start + timedelta(hours=2),
        )

    def appointment(self, start, finish):
        return {
            "mascota": self.pet.pk, "profesional": self.vet.pk, "motivo": "Control",
            "estado": "agendada", "inicio": start, "fin": finish,
        }

    def test_branding_and_role_restrictions(self):
        anonymous = Client()
        self.assertRedirects(anonymous.get("/"), "/ingresar/?next=/")
        self.assertContains(anonymous.get("/ingresar/"), "Veterinaria San Francisco")
        self.assertEqual(anonymous.get("/api/tutores/").status_code, 403)
        self.assertEqual(self.client.get("/cuentas/").status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get("/").status_code, 403)
        self.assertEqual(self.client.get("/api/tutores/").status_code, 403)
        self.client.force_login(self.manager)
        self.assertContains(self.client.get("/cuentas/"), "Nueva cuenta de administración")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post("/api/tutores/", {}, content_type="application/json").status_code, 403)

    def test_templates_and_api_enforce_same_calendar(self):
        finish = self.start + timedelta(minutes=30)
        data = self.appointment(self.start, finish)
        form = {**data, "inicio": self.start.strftime("%Y-%m-%dT%H:%M"),
                "fin": finish.strftime("%Y-%m-%dT%H:%M")}
        self.assertEqual(self.client.post("/gestion/citas/nuevo/", form).status_code, 302)
        self.assertContains(self.client.get(reverse("calendar", query={"fecha": self.start.date()})), "Nube")
        overlapping = self.client.post("/api/citas/", data, content_type="application/json")
        self.assertContains(overlapping, "ya tiene una cita", status_code=400)
        outside = self.appointment(self.start - timedelta(minutes=30), finish)
        response = self.client.post("/api/citas/", outside, content_type="application/json")
        self.assertContains(response, "dentro de un bloque", status_code=400)
        adjacent = self.appointment(finish, finish + timedelta(minutes=30))
        self.assertEqual(self.client.post("/api/citas/", adjacent, content_type="application/json").status_code, 201)
        self.assertEqual(self.client.delete(f"/api/disponibilidad/{self.window.pk}/").status_code, 409)
        self.assertEqual(Cita.objects.count(), 2)

    def test_clinical_record_on_pet_profile_and_protected_tutor(self):
        response = self.client.post("/api/atenciones/", {
            "mascota": self.pet.pk, "profesional": self.vet.pk, "diagnostico": "Control normal",
            "tratamiento": "Reposo", "receta": "Indicaciones", "examenes": "Hemograma",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertContains(self.client.get(f"/gestion/mascotas/{self.pet.pk}/"), "Control normal")
        self.assertEqual(self.client.delete(f"/api/tutores/{self.tutor.pk}/").status_code, 409)

    def test_inventory_rejects_overdraw_without_creating_movement(self):
        item = Insumo.objects.create(codigo="GUA", nombre="Guantes", categoria="Protección")
        endpoint = "/api/movimientos/"
        payload = {"insumo": item.pk, "tipo": "entrada", "cantidad": 5, "motivo": "Reposición"}
        receipt = self.client.post(endpoint, payload, content_type="application/json")
        self.assertEqual(receipt.status_code, 201)
        self.assertEqual(self.client.delete(f"{endpoint}{receipt.json()['id']}/").status_code, 405)
        payload.update(tipo="salida", cantidad=6)
        self.assertEqual(self.client.post(endpoint, payload, content_type="application/json").status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)
        self.assertEqual(Movimiento.objects.count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_reminder_retries_then_sends_once_and_schedules_next(self):
        today = timezone.localdate()
        reminder = save_record(Recordatorio(
            mascota=self.pet, tipo="control", detalle="Revisión", fecha_objetivo=today + timedelta(days=3),
            anticipacion_dias=3, repetir_dias=30,
        ), user=self.staff)
        with patch("clinic.management.commands.enviar_recordatorios.send_mail", return_value=0):
            with self.assertRaisesMessage(CommandError, "No se pudieron enviar"):
                call_command("enviar_recordatorios", stdout=StringIO(), stderr=StringIO())
        reminder.refresh_from_db()
        self.assertIsNone(reminder.enviado_en)
        call_command("enviar_recordatorios", stdout=StringIO())
        call_command("enviar_recordatorios", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.tutor.email])
        next_reminder = Recordatorio.objects.exclude(pk=reminder.pk).get()
        self.assertEqual(next_reminder.enviar_el, today + timedelta(days=30))
        self.assertEqual(self.client.delete(f"/api/recordatorios/{reminder.pk}/").status_code, 403)


    def admin_appointment(self, start, finish):
        return {
            "mascota": self.pet.pk, "profesional": self.vet.pk, "motivo": "Vacuna", "estado": "agendada",
            "inicio_0": start.strftime("%Y-%m-%d"), "inicio_1": start.strftime("%H:%M:%S"),
            "fin_0": finish.strftime("%Y-%m-%d"), "fin_1": finish.strftime("%H:%M:%S"),
        }

    def test_django_admin_registers_models_and_applies_rules(self):
        models_ = ("tutor", "mascota", "profesional", "disponibilidad", "cita", "atencion",
                   "recordatorio", "insumo", "movimiento")
        self.assertContains(self.client.get("/admin/"), "Veterinaria San Francisco")
        for name in models_:
            self.assertEqual(self.client.get(f"/admin/clinic/{name}/").status_code, 200, name)
            self.assertEqual(self.client.get(f"/admin/clinic/{name}/add/").status_code, 200, name)
        self.assertEqual(self.client.get("/admin/clinic/cita/?q=Nube&estado__exact=agendada").status_code, 200)
        self.assertEqual(self.client.get("/admin/auth/user/").status_code, 403)

        finish = self.start + timedelta(minutes=30)
        created = self.client.post("/admin/clinic/cita/add/", self.admin_appointment(self.start, finish))
        self.assertEqual(created.status_code, 302)
        clash = self.client.post("/admin/clinic/cita/add/", self.admin_appointment(self.start, finish))
        self.assertContains(clash, "ya tiene una cita")
        self.assertEqual(Cita.objects.count(), 1)
        self.assertEqual(self.client.get(f"/admin/clinic/disponibilidad/{self.window.pk}/delete/").status_code, 403)

        item = Insumo.objects.create(codigo="VAC", nombre="Vacuna", categoria="Biológicos")
        movement = {"insumo": item.pk, "tipo": "salida", "cantidad": 2, "motivo": "Uso"}
        self.assertContains(self.client.post("/admin/clinic/movimiento/add/", movement), "stock fuera")
        movement["tipo"] = "entrada"
        self.assertEqual(self.client.post("/admin/clinic/movimiento/add/", movement).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.stock, 2)
        self.assertEqual(Movimiento.objects.get().registrado_por, self.staff)

        sent = Recordatorio.objects.create(
            mascota=self.pet, tipo="vacuna", detalle="Triple felina", fecha_objetivo=timezone.localdate(),
            enviar_el=timezone.localdate(), enviado_en=timezone.now(),
        )
        for url in (f"/admin/clinic/tutor/{self.tutor.pk}/change/", f"/admin/clinic/mascota/{self.pet.pk}/change/",
                    f"/admin/clinic/insumo/{item.pk}/change/", f"/admin/clinic/recordatorio/{sent.pk}/change/",
                    f"/admin/clinic/movimiento/{Movimiento.objects.get().pk}/change/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertNotContains(self.client.get(f"/admin/clinic/recordatorio/{sent.pk}/change/"), 'name="_save"')

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_demo_data_loads_once_and_respects_rules(self):
        Disponibilidad.objects.all().delete()
        Mascota.objects.all().delete()
        Tutor.objects.all().delete()
        Profesional.objects.all().delete()
        out = StringIO()
        call_command("datos_demo", stdout=out)
        self.assertIn("Datos de demostración cargados", out.getvalue())
        self.assertEqual(Tutor.objects.count(), 5)
        self.assertEqual(Cita.objects.count(), 30)
        self.assertTrue(Insumo.objects.filter(stock__lte=models.F("minimo")).exists())
        self.assertEqual(Recordatorio.objects.filter(enviar_el__lte=timezone.localdate()).count(), 2)
        call_command("datos_demo", stdout=out)
        self.assertEqual(Tutor.objects.count(), 5)
