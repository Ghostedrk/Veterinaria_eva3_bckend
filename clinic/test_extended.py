"""Pruebas de la ficha extendida, enlaces del tutor, consentimientos, estadísticas y reportes."""
import base64
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import tutor
from .models import Adjunto, Atencion, Cita, Consentimiento, Disponibilidad, Mascota, Profesional, Servicio, Tutor
from .roles import RECEPCION
from .services import save_record

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

TEMP_MEDIA = tempfile.mkdtemp(prefix="petcare-test-media-")


@override_settings(MEDIA_ROOT=TEMP_MEDIA, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   SITE_URL="https://petcare.example.test")
class ExtendedFlows(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.manager = users.create_user("jefa", is_staff=True, is_superuser=True)
        cls.staff = users.create_user("admin1", is_staff=True)
        cls.reception = users.create_user("recep1", is_staff=True)
        cls.reception.groups.add(Group.objects.get_or_create(name=RECEPCION)[0])
        cls.tutor = Tutor.objects.create(nombre="Ana Demo", email="ana@example.test", telefono="555")
        cls.pet = Mascota.objects.create(tutor=cls.tutor, nombre="Nube", especie="Gato")
        cls.vet = Profesional.objects.create(nombre="Dra. Demo", especialidad="Medicina general")
        cls.service = Servicio.objects.create(nombre="Consulta general", precio=18000)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.staff)

    def visit(self, **extra):
        return save_record(Atencion(mascota=self.pet, profesional=self.vet, diagnostico="Control", **extra),
                           user=self.staff)

    def test_service_price_weight_curve_and_no_show(self):
        visit = self.visit(servicio=self.service, peso_kg=Decimal("4.20"))
        self.assertEqual(visit.monto, 18000)  # Toma el precio del servicio.
        self.visit(servicio=self.service, monto=12000, peso_kg=Decimal("4.60"),
                   fecha=timezone.localdate() + timedelta(days=0))
        page = self.client.get(f"/gestion/mascotas/{self.pet.pk}/")
        self.assertContains(page, "Control de peso")
        self.assertContains(page, "<polyline", html=False)
        self.assertEqual(page.context["weight"]["count"], 2)
        self.assertNotRegex(page.content.decode(), r'c[xy]="[0-9]+,[0-9]')  # Coordenadas SVG con punto.
        # Recepción ve servicios pero no los modifica.
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get("/gestion/servicios/").status_code, 200)
        self.assertEqual(self.client.get("/gestion/servicios/nuevo/").status_code, 403)

    def test_attachments_are_validated_and_private(self):
        visit = self.visit()
        url = f"/atenciones/{visit.pk}/adjuntos/"
        fake = SimpleUploadedFile("informe.pdf", b"no es un pdf", content_type="application/pdf")
        self.client.post(url, {"tipo": "laboratorio", "archivo": fake})
        self.assertFalse(Adjunto.objects.exists())
        pdf = SimpleUploadedFile("hemograma.pdf", b"%PDF-1.4\n%demo\n", content_type="application/pdf")
        self.client.post(url, {"tipo": "laboratorio", "descripcion": "Hemograma", "archivo": pdf})
        attachment = Adjunto.objects.get()
        self.assertEqual(attachment.nombre_original, "hemograma.pdf")
        self.assertNotIn("hemograma", attachment.archivo.name)
        response = self.client.get(f"/adjuntos/{attachment.pk}/")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(b"".join(response.streaming_content)[:4], b"%PDF")
        self.assertEqual(Client().get(f"/adjuntos/{attachment.pk}/").status_code, 302)
        self.assertContains(self.client.get(f"/gestion/atenciones/{visit.pk}/"), "Hemograma")
        self.client.post(f"/adjuntos/{attachment.pk}/eliminar/")
        self.assertFalse(Adjunto.objects.exists())

    def appointment(self, hours_ahead=20):
        start = timezone.now().replace(microsecond=0) + timedelta(hours=hours_ahead)
        Disponibilidad.objects.create(profesional=self.vet, inicio=start - timedelta(hours=1),
                                      fin=start + timedelta(hours=2))
        return save_record(Cita(mascota=self.pet, profesional=self.vet, inicio=start,
                                fin=start + timedelta(minutes=30), motivo="Vacuna"), user=self.staff)

    def test_tutor_confirms_or_cancels_from_link_without_login(self):
        cita = self.appointment()
        call_command("enviar_recordatorios", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        link = tutor.appointment_url(cita)
        self.assertIn(link, mail.outbox[0].body)
        self.assertTrue(link.startswith("https://petcare.example.test/tutor/cita/"))
        path = link.replace("https://petcare.example.test", "")
        anonymous = Client()
        self.assertContains(anonymous.get(path), "Confirmar asistencia")
        anonymous.post(path, {"respuesta": "confirmar"})
        cita.refresh_from_db()
        self.assertEqual(cita.respuesta_tutor, Cita.Respuesta.CONFIRMADA)
        anonymous.post(path, {"respuesta": "cancelar"})
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.Estado.CANCELADA)
        self.assertContains(anonymous.post(path, {"respuesta": "confirmar"}), "ya no admite cambios")
        self.assertEqual(anonymous.get(path[:-6] + "abcdef/").status_code, 404)
        call_command("enviar_recordatorios", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)  # Nunca se envía dos veces.

    def test_consent_signed_by_tutor_and_locked(self):
        self.client.post("/consentimientos/nuevo/", {
            "mascota": self.pet.pk, "profesional": self.vet.pk, "procedimiento": "cirugia",
            "fecha_procedimiento": timezone.localdate().isoformat(),
            "descripcion": "Esterilización", "riesgos": "Riesgo anestésico",
        })
        consent = Consentimiento.objects.get()
        self.assertEqual(consent.creado_por, self.staff)
        path = tutor.consent_url(consent).replace("https://petcare.example.test", "")
        anonymous = Client()
        self.assertContains(anonymous.post(path, {"respuesta": "autorizar", "nombre": "Ana Demo", "firma": ""}),
                            "Dibuja tu firma")
        signature = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
        anonymous.post(path, {"respuesta": "autorizar", "nombre": "Ana Demo", "rut": "11.111.111-1",
                              "firma": signature})
        consent.refresh_from_db()
        self.assertEqual(consent.estado, Consentimiento.Estado.AUTORIZADO)
        self.assertEqual(consent.firmante_nombre, "Ana Demo")
        self.assertContains(anonymous.post(path, {"respuesta": "rechazar", "nombre": "Otra"}), "ya fue respondido")
        self.assertContains(self.client.get(f"/consentimientos/{consent.pk}/"), signature[:60])

    def test_dashboard_for_jefatura_and_exports(self):
        self.visit(servicio=self.service)
        cita = self.appointment(hours_ahead=-30)
        Cita.objects.filter(pk=cita.pk).update(estado=Cita.Estado.NO_ASISTIO)
        self.assertEqual(self.client.get("/estadisticas/").status_code, 403)
        self.client.force_login(self.manager)
        start = (timezone.localdate() - timedelta(days=5)).isoformat()
        page = self.client.get("/estadisticas/", {"desde": start})
        self.assertEqual(page.status_code, 200)
        m = page.context["m"]
        self.assertEqual((m["income"], m["ticket"], m["missed"], m["no_show"]), (18000, 18000, 1, 100.0))
        self.assertEqual(m["ranking"][0]["name"], "Consulta general")
        self.assertContains(page, "$18.000")

        self.client.force_login(self.staff)
        for kind in ("clinico", "contable"):
            pdf = self.client.get("/reportes/descargar/", {"tipo": kind, "formato": "pdf", "desde": start})
            self.assertEqual(pdf["Content-Type"], "application/pdf")
            self.assertTrue(pdf.content.startswith(b"%PDF"))
            xlsx = self.client.get("/reportes/descargar/", {"tipo": kind, "formato": "xlsx", "desde": start})
            self.assertTrue(xlsx.content.startswith(b"PK"))
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(xlsx.content))
        self.assertEqual(book.sheetnames, ["Ingresos", "Egresos"])
        self.assertEqual(book["Ingresos"]["E5"].value, 18000)
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get("/reportes/").status_code, 403)
