"""Pruebas de la Evaluación 4: JWT, API Gateway, hashing de contraseñas, CRUD JSON y CORS."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import Mascota, Tutor

PASSWORD = "Huellas-Seguras-2026"


class Eva4Api(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("vet.api", password=PASSWORD, is_staff=True)
        cls.outsider = get_user_model().objects.create_user("externo", password=PASSWORD)

    def setUp(self):
        cache.clear()  # Los contadores de throttling viven en la caché.

    def tokens(self, username="vet.api"):
        response = self.client.post("/api/token/", {"username": username, "password": PASSWORD},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def auth(self, access):
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def test_password_is_hashed_with_argon2(self):
        stored = get_user_model().objects.get(username="vet.api").password
        self.assertTrue(stored.startswith("argon2$argon2id$"))
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_jwt_protects_crud_and_returns_json(self):
        self.assertEqual(self.client.get("/api/tutores/").status_code, 401)
        bad = self.client.post("/api/token/", {"username": "vet.api", "password": "x"},
                               content_type="application/json")
        self.assertEqual(bad.status_code, 401)
        tokens = self.tokens()
        headers = self.auth(tokens["access"])
        self.assertEqual(self.client.get("/api/yo/", **headers).json()["rol"], "Administración")

        created = self.client.post("/api/tutores/", {"nombre": "Ana", "email": "ana@example.test", "telefono": "555"},
                                   content_type="application/json", **headers)
        self.assertEqual(created.status_code, 201)
        tutor_id = created.json()["id"]
        invalid = self.client.post("/api/tutores/", {"nombre": "Sin correo", "email": "no-es-correo"},
                                   content_type="application/json", **headers)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("email", invalid.json())
        pet = self.client.post("/api/mascotas/", {"tutor": tutor_id, "nombre": "Nube", "especie": "Gato"},
                               content_type="application/json", **headers)
        self.assertEqual(pet.status_code, 201)
        self.assertEqual(self.client.patch(f"/api/tutores/{tutor_id}/", {"telefono": "777"},
                                           content_type="application/json", **headers).status_code, 200)
        self.assertEqual(self.client.put(f"/api/tutores/{tutor_id}/", {
            "nombre": "Ana Pérez", "email": "ana@example.test", "telefono": "777", "direccion": "Calle 1"},
            content_type="application/json", **headers).status_code, 200)
        self.assertEqual(Tutor.objects.get().nombre, "Ana Pérez")
        # El tutor con mascotas está protegido: 409 en vez de borrar en cascada.
        self.assertEqual(self.client.delete(f"/api/tutores/{tutor_id}/", **headers).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/mascotas/{pet.json()['id']}/", **headers).status_code, 204)
        self.assertEqual(self.client.delete(f"/api/tutores/{tutor_id}/", **headers).status_code, 204)
        self.assertFalse(Mascota.objects.exists())

        # Un usuario sin rol de personal obtiene token, pero no accede a los recursos.
        outsider = self.auth(self.tokens("externo")["access"])
        self.assertEqual(self.client.get("/api/tutores/", **outsider).status_code, 403)

    def test_refresh_rotation_and_logout_blacklist(self):
        tokens = self.tokens()
        refreshed = self.client.post("/api/token/refresh/", {"refresh": tokens["refresh"]},
                                     content_type="application/json")
        self.assertEqual(refreshed.status_code, 200)
        new_refresh = refreshed.json()["refresh"]
        # El refresh anterior quedó en la lista negra tras la rotación.
        self.assertEqual(self.client.post("/api/token/refresh/", {"refresh": tokens["refresh"]},
                                          content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post("/api/token/logout/", {"refresh": new_refresh},
                                          content_type="application/json").status_code, 200)
        self.assertEqual(self.client.post("/api/token/refresh/", {"refresh": new_refresh},
                                          content_type="application/json").status_code, 401)

    @override_settings(API_GATEWAY_SECRET="secreto-de-prueba")
    def test_api_only_through_gateway_header(self):
        self.assertEqual(self.client.get("/api/salud/").status_code, 403)
        self.assertEqual(self.client.get("/api/salud/", HTTP_X_PETCARE_GATEWAY="otro").status_code, 403)
        ok = self.client.get("/api/salud/", HTTP_X_PETCARE_GATEWAY="secreto-de-prueba")
        self.assertEqual(ok.json()["status"], "ok")
        # El panel web y su login no pasan por API Gateway.
        self.assertEqual(self.client.get("/ingresar/").status_code, 200)

    def test_login_is_throttled(self):
        codes = [self.client.post("/api/token/", {"username": "vet.api", "password": "mala"},
                                  content_type="application/json").status_code for _ in range(12)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 401)

    @override_settings(CORS_ALLOWED_ORIGINS=["http://frontend.example.test"])
    def test_cors_allows_only_the_frontend(self):
        allowed = self.client.options("/api/tutores/", HTTP_ORIGIN="http://frontend.example.test",
                                      HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertEqual(allowed["access-control-allow-origin"], "http://frontend.example.test")
        other = self.client.options("/api/tutores/", HTTP_ORIGIN="http://evil.example.test",
                                    HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("access-control-allow-origin", other)

    def test_api_security_headers_from_zap_findings(self):
        response = self.client.get("/api/salud/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_openapi_docs_require_staff_session(self):
        self.assertEqual(self.client.get("/docs/api/schema/").status_code, 401)
        self.client.force_login(self.user)
        schema = self.client.get("/docs/api/schema/")
        self.assertEqual(schema.status_code, 200)
        self.assertIn(b"/api/token/", schema.content)
