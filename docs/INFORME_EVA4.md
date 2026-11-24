# Informe técnico · Evaluación 4 · Programación Backend

**Proyecto:** PetCare · Veterinaria San Francisco (Proyecto 1)
**Repositorio:** https://github.com/Ghostedrk/Veterinaria_eva3_bckend
**Backend (panel y Django Admin):** https://petcare-sfvet.duckdns.org · EC2 `petcare-eva3` (IP elástica 44.213.33.107)
**Frontend:** http://`<IP-FRONTEND>`/ · EC2 `petcare-frontend`
**API pública:** `https://<ID>.execute-api.us-east-1.amazonaws.com/api/` (Amazon API Gateway, HTTP API)
**Documentación de la API:** https://petcare-sfvet.duckdns.org/docs/api/ (OpenAPI 3 / Swagger, requiere sesión del personal)

> Las capturas se identifican como **E01, E02…** según el índice de la sección 1. Cada una muestra una configuración o un resultado verificable, no solo el nombre del servicio.

---

## 1. Índice de evidencias

| N.º | Evidencia | Qué debe mostrar la captura | Criterio |
|---|---|---|---|
| E01 | Diagrama de arquitectura | Sección 2 de este informe | P3 |
| E02 | Frontend: inicio de sesión | Pantalla de login del frontend en la EC2 frontend | P2, P4 |
| E03 | Frontend: crear registro | Formulario y mensaje "Registro creado (201 Created)" | P1, P2 |
| E04 | Persistencia en RDS | Consulta `psql` a RDS que muestra el registro recién creado | P2 |
| E05 | Documentación de la API | `/docs/api/` (Swagger) con los endpoints | P1 |
| E06 | Pruebas HTTP con JWT | Terminal: token, GET/POST/PATCH/PUT/DELETE y códigos 200/201/204/400/401/403/409 | P1, P4 |
| E07 | Pruebas automáticas | `manage.py test` con las 23 pruebas en OK | P1 |
| E08 | Hash de contraseñas | `PASSWORD_HASHERS` y un hash `argon2$argon2id$…` en la base | P4 |
| E09 | SonarQube: resumen | Panel del proyecto en SonarQube Cloud (bugs, vulnerabilidades, hotspots) | P5 |
| E10 | SonarQube: hallazgo corregido | Detalle del hallazgo, commit con la corrección y nuevo análisis | P5 |
| E11 | OWASP ZAP: resumen | Informe ZAP Baseline con las alertas por nivel de riesgo | P5 |
| E12 | OWASP ZAP: hallazgo analizado | Alerta concreta, su causa y tratamiento | P5 |
| E13 | API Gateway: rutas e integración | Ruta `ANY /api/{proxy+}` integrada con el backend | P6 |
| E14 | API Gateway: mapeo de parámetros | Cabecera `x-petcare-gateway` agregada en la integración (valor oculto) | P6 |
| E15 | API Gateway: throttling | Etapa `$default`: velocidad 2 req/s, ráfaga 5 | P6 |
| E16 | Prueba del rate limit | Salida de `rate-limit-test.ps1` con respuestas 200 y 429 | P6 |
| E17 | Bloqueo del acceso directo | `curl` directo a la EC2 → 403; vía API Gateway → 200 | P6 |
| E18 | RDS: configuración | Instancia `petcare-db`: motor, clase, no pública, VPC | P3, P7 |
| E19 | RDS: cifrado en reposo | "Cifrado: Habilitado" con la clave KMS `aws/rds` | P7 |
| E20 | RDS: Security Group | Regla 5432 con origen = SG de la EC2 backend (sin IP abiertas) | P7 |
| E21 | RDS: conexión TLS desde Django | Salida de `migrate-to-rds.sh`: `ssl = true`, host de RDS | P3, P7 |
| E22 | S3: bucket y cifrado | Bucket con SSE-S3 y control de versiones habilitado | P7 |
| E23 | S3: Block Public Access | Los cuatro bloqueos activados | P7 |
| E24 | S3: archivos de la app | Objetos `static/` y `media/` en el bucket | P3 |
| E25 | S3: URL prefirmada | Descarga de un adjunto o PDF con `X-Amz-Signature` y `X-Amz-Expires` | P7 |
| E26 | IAM: rol de la EC2 | `LabInstanceProfile` asignado a la EC2 backend | P7 |
| E27 | CloudWatch: métricas | `CPUUtilization` y otras métricas de la EC2 | P8 |
| E28 | CloudWatch: alarma | Alarma de CPU con umbral, periodo y acción SNS | P8 |
| E29 | SNS: suscripción | Tema `petcare-alertas` con la suscripción de correo confirmada | P8 |
| E30 | RDS: respaldos automáticos | Retención de 7 días y ventana de respaldo | P8 |
| E31 | RDS: snapshot manual | Snapshot manual en estado "Disponible" | P8 |
| E32 | Lambda + EventBridge cada 7 h | Función, regla `rate(7 hours)` y registro en CloudWatch Logs | P8 (ampliación) |

---

## 2. Arquitectura

```
                        ┌─────────────────────────────┐
   Navegador ──HTTP──▶  │ EC2 frontend (Nginx)        │  HTML + JS + CSS, CSP estricta
                        └──────────────┬──────────────┘
                                       │ fetch() JSON + Authorization: Bearer <JWT>
                                       ▼
                        ┌─────────────────────────────┐
                        │ Amazon API Gateway (HTTP API)│  throttling 2 req/s · ráfaga 5
                        │ ANY /api/{proxy+}            │  agrega cabecera secreta
                        └──────────────┬──────────────┘
                                       │ HTTPS
                                       ▼
   Panel y Django Admin  ┌─────────────────────────────┐   rol IAM    ┌──────────────────────┐
   (personal, HTTPS) ──▶ │ EC2 backend                 │ ───────────▶ │ S3 privado (SSE-S3)  │
                         │ Nginx → Gunicorn → Django   │              │ static/ media/       │
                         │ REST Framework + SimpleJWT  │              │ reportes/ (PDF)      │
                         └──────────────┬──────────────┘              └──────────────────────┘
                                        │ TLS (verify-full) · puerto 5432 solo desde el SG backend
                                        ▼
                         ┌─────────────────────────────┐
                         │ Amazon RDS PostgreSQL       │  cifrado KMS · sin acceso público
                         │ respaldos automáticos 7 días│
                         └──────────────▲──────────────┘
                                        │ CreateDBSnapshot
   EventBridge rate(7 hours) ──▶ Lambda rds_snapshot ──▶ SNS petcare-alertas ──▶ correo
   CloudWatch: métricas EC2/RDS, alarma CPU ──────────────▶ SNS petcare-alertas
   SonarQube Cloud (SAST, sobre el código)   ·   OWASP ZAP Baseline (DAST, sobre la app desplegada)
```

| Componente | Implementación | Por qué |
|---|---|---|
| EC2 frontend | Nginx sirve `frontend/` (JS sin compilación) | Separa la interfaz del procesamiento; CSP solo permite su origen y la URL de la API |
| EC2 backend | Django 5.2 + DRF + Gunicorn + Nginx | Procesa la lógica de negocio; no guarda datos ni archivos localmente |
| RDS PostgreSQL | `petcare-db`, db.t3.micro, cifrada, privada | Persistencia administrada, con respaldos y separada de la EC2 |
| S3 | Bucket privado con SSE-S3 y versionado | Estáticos, adjuntos clínicos y reportes PDF/Excel |
| API Gateway | HTTP API con throttling por etapa | Punto único de entrada a la API y limitación de solicitudes |
| CloudWatch + SNS | Alarma de CPU y avisos por correo | Observabilidad y alertas |
| Lambda + EventBridge | Snapshot cada 7 h con rotación | Respaldo adicional con la frecuencia pedida |
| JWT | SimpleJWT: access 15 min, refresh 12 h con rotación y lista negra | Autenticación sin estado para el frontend |

---

## 3. Actividad 1 · API RESTful e integración

### 3.1 Configuración de Django REST Framework

`petcare/settings.py`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAdminUser"],
    "DEFAULT_PAGINATION_CLASS": "clinic.pagination.Pagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"login": "10/min"},
}
```

### 3.2 Entidades relacionadas

`Tutor` 1—N `Mascota` 1—N `Cita` N—1 `Profesional` 1—N `Disponibilidad`; `Mascota` 1—N `Atencion` N—1 `Servicio`; `Atencion` 1—N `Adjunto`; `Mascota` 1—N `Recordatorio` y `Consentimiento`; `Insumo` 1—N `Movimiento`; `OrdenCompra` 1—N `ItemOrden` N—1 `Insumo`. En total son **15 modelos** con claves foráneas `PROTECT`, que impiden borrar un registro con historial.

### 3.3 Endpoints

| Método y ruta | Descripción | Respuestas |
|---|---|---|
| `POST /api/token/` | Login: entrega `access` y `refresh` | 200, 401, 429 |
| `POST /api/token/refresh/` | Nuevo access; rota el refresh | 200, 401 |
| `POST /api/token/logout/` | Pone el refresh en la lista negra | 200, 401 |
| `GET /api/yo/` | Perfil y rol del token | 200, 401 |
| `GET /api/salud/` | Estado de la API y de la base (público) | 200 |
| `GET, POST /api/{recurso}/` | Listar (paginado, `?search=`) y crear | 200, 201, 400, 401, 403 |
| `GET, PUT, PATCH, DELETE /api/{recurso}/{id}/` | Leer, reemplazar, modificar y eliminar | 200, 204, 400, 403, 404, 409 |

Los recursos son `tutores`, `mascotas`, `profesionales`, `servicios`, `disponibilidad`, `citas`, `atenciones`, `recordatorios`, `insumos` y `movimientos`. Este último es de solo lectura y creación, porque funciona como historial. Todos tienen *serializers* `ModelSerializer` generados desde `clinic/resources.py` y validaciones en `clinic/services.py`:
- Cruces de horario de citas.
- Citas solo dentro de la disponibilidad.
- Stock que nunca queda negativo.
- Profesionales y servicios inactivos.
- Fechas en el futuro.

Las reglas de negocio responden **400** con el detalle por campo. Las relaciones protegidas y los conflictos responden **409**.

### 3.4 Ejemplos de prueba (E06)

```bash
API=https://<ID>.execute-api.us-east-1.amazonaws.com
TOKEN=$(curl -s -X POST $API/api/token/ -H 'Content-Type: application/json' \
        -d '{"username":"<usuario>","password":"<contraseña>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')
curl -s $API/api/tutores/                                   # 401: sin token
curl -s $API/api/tutores/ -H "Authorization: Bearer $TOKEN" # 200: lista JSON paginada
curl -s -X POST $API/api/tutores/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"nombre":"Prueba API","email":"prueba@example.test","telefono":"555"}'   # 201
curl -s -X POST $API/api/tutores/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"nombre":"","email":"no-es-correo"}'                                    # 400 con errores por campo
curl -s -X PATCH  $API/api/tutores/<id>/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"telefono":"777"}'  # 200
curl -s -X DELETE $API/api/tutores/<id>/ -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'                             # 204
```

### 3.5 Frontend e integración (E02–E04)

El frontend (`frontend/app.js`) realiza un CRUD completo de **tutores, mascotas, citas y atenciones** con `fetch()` y JSON:
- **Login:** `POST /api/token/`. El *access token* se guarda **solo en memoria** y el *refresh* en `sessionStorage`, que se borra al cerrar la pestaña.
- **Renovación:** ante un 401 renueva el token una vez con `/api/token/refresh/`.
- **Cierre de sesión:** invalida el refresh con `/api/token/logout/`.
- **Mensajes:** muestra los errores 400 junto a cada campo, y los 403, 409 y 429 con un mensaje claro.
- **Registro de solicitudes:** guarda las últimas solicitudes (método, ruta, código y tiempo), que se usan en la demostración.

Para verificar la persistencia en RDS (E04), desde la EC2 backend:

```bash
sudo petcare-manage dbshell -- -c "SELECT id, nombre, especie FROM clinic_mascota ORDER BY id DESC LIMIT 3;"
```

---

## 4. Actividad 2 · Desarrollo seguro: SAST y DAST

### 4.1 SonarQube (SAST) · E09, E10

**Herramienta:** SonarQube Cloud (el servicio SaaS de SonarSource, antes SonarCloud), conectado al repositorio de GitHub con *Automatic Analysis*. La configuración está en `sonar-project.properties`: analiza `clinic/`, `petcare/`, `frontend/` y `deploy/`, y excluye las migraciones.

| Métrica | Resultado |
|---|---|
| Bugs | _completar_ |
| Vulnerabilidades | _completar_ |
| Security Hotspots | _completar_ |
| Code Smells | _completar_ |
| Duplicación | _completar_ |

**Hallazgo analizado:** _regla, archivo y línea_ → _causa_ → _corrección (commit)_ o _justificación técnica_.

### 4.2 OWASP ZAP (DAST) · E11, E12

**Ejecución:** `deploy/zap-scan.sh`, que usa ZAP Baseline en Docker desde la EC2 frontend. Es un entorno propio y autorizado. Baseline hace una exploración (*spider*) y un **análisis pasivo**, sin ataques ni cambios de datos.

```bash
sudo bash /opt/petcare-src/deploy/zap-scan.sh http://<IP-FRONTEND>/ https://petcare-sfvet.duckdns.org/ https://<ID>.execute-api.us-east-1.amazonaws.com/api/salud/
```

| Objetivo | Alta | Media | Baja | Informativa |
|---|---|---|---|---|
| Frontend | _ | _ | _ | _ |
| Backend (panel) | _ | _ | _ | _ |
| API Gateway | _ | _ | _ | _ |

**Hallazgo analizado:** _alerta, URL, riesgo y confianza_ → _causa_ → _tratamiento_.

### 4.3 Comparación SAST y DAST

| | SAST (SonarQube) | DAST (OWASP ZAP) |
|---|---|---|
| Qué analiza | El código fuente, sin ejecutarlo | La aplicación en ejecución, desde afuera, por HTTP |
| Cuándo | Durante el desarrollo, en cada commit o PR | Con la app desplegada (pruebas o preproducción) |
| Qué detecta | Inyecciones en el código, secretos escritos en el código, criptografía débil, errores de lógica, código duplicado o difícil de mantener | Cabeceras de seguridad ausentes, cookies sin `Secure`/`HttpOnly`, exposición de información, XSS reflejado, configuración del servidor |
| Ventaja | Indica archivo y línea exactos, y es barato de corregir temprano | No requiere el código; ve la configuración real (Nginx, TLS, cabeceras) |
| Limitación | Falsos positivos; no ve la configuración ni el entorno | Solo ve lo que alcanza a recorrer; no indica la línea; el modo pasivo no prueba ataques activos |

Ambas herramientas se complementan: SAST protege el código y DAST protege el despliegue.

---

## 5. Actividad 3 · Contraseñas y criptografía

### 5.1 Configuración (E08)

```python
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",   # predeterminado: Argon2id
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",   # hashes antiguos, se actualizan al iniciar sesión
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
```

Demostración en la EC2 backend:

```bash
sudo petcare-manage shell -c "from django.contrib.auth import get_user_model as g; u=g().objects.order_by('-last_login').first(); print(u.username, u.password[:60] + '...')"
```

El resultado tiene el formato `argon2$argon2id$v=19$m=102400,t=2,p=8$<salt>$<hash>`: algoritmo, parámetros de costo, *salt* aleatorio y hash. La contraseña **nunca** se guarda ni se puede recuperar. Django la verifica volviendo a calcular el hash con `check_password()`, que compara en tiempo constante. La prueba `test_password_is_hashed_with_argon2` lo comprueba de forma automática.

### 5.2 Conceptos

**Función hash.** Transforma un mensaje de cualquier largo en un resumen de largo fijo. Sus propiedades son:
- **Determinista:** la misma entrada siempre produce la misma salida.
- **Resistente a preimagen:** no se puede obtener la entrada a partir del hash.
- **Resistente a segunda preimagen:** dada una entrada, no se puede encontrar otra con el mismo hash.
- **Resistente a colisiones:** no se pueden encontrar dos entradas con el mismo hash.
- **Efecto avalancha:** un bit distinto cambia por completo el resultado.

**Hash, cifrado y codificación.**

| | Hash | Cifrado | Codificación |
|---|---|---|---|
| ¿Reversible? | No (unidireccional) | Sí, con la clave | Sí, sin clave |
| Usa clave | No (HMAC sí) | Sí (simétrica o asimétrica) | No |
| Propósito | Integridad y verificación de contraseñas | Confidencialidad | Representar datos (Base64, URL) |
| En PetCare | Argon2 (contraseñas), firma HMAC de los JWT | TLS hacia RDS y API, SSE-S3, KMS en RDS | Base64 en los JWT y en la firma del consentimiento |

**MD5.** Produce un hash de 128 bits. No sirve para contraseñas porque:
- Tiene colisiones prácticas desde 2004.
- Es **extremadamente rápido**: una GPU calcula miles de millones por segundo, lo que permite fuerza bruta y diccionarios.
- No incluye *salt*, así que es vulnerable a tablas arcoíris.

**SHA (Secure Hash Algorithm).**
- **SHA-1** (160 bits): roto, con colisión práctica *SHAttered* en 2017.
- **SHA-2** (SHA-224/256/384/512): estructura Merkle-Damgård, vigente y seguro.
- **SHA-3** (Keccak, estándar desde 2015): estructura de esponja distinta, sirve como alternativa si SHA-2 se debilitara.

Ninguno es adecuado por sí solo para contraseñas, porque **son rápidos a propósito**.

**Salt.** Es un valor aleatorio único por contraseña, generado con un generador criptográfico (`secrets` y `os.urandom` en Django). Se guarda junto al hash, no es secreto. Sirve para que:
- Dos usuarios con la misma contraseña tengan hashes distintos.
- No sirvan las tablas precalculadas (arcoíris).
- El atacante tenga que atacar cada cuenta por separado.

**PBKDF2 y Argon2 en Django.** Django guarda `algoritmo$parámetros$salt$hash`.
- **PBKDF2-SHA256** aplica SHA-256 cientos de miles de veces (1.000.000 de iteraciones en Django 5.2) para que cada intento sea lento.
- **Argon2id**, ganador de la Password Hashing Competition 2015 y recomendado por OWASP, además consume **memoria** (100 MiB en Django). Eso encarece los ataques con GPU y ASIC.

Al iniciar sesión, si el hash usa un algoritmo o costo antiguo, Django lo **actualiza** solo. Por eso, agregar Argon2 primero no invalidó las contraseñas existentes.

---

## 6. Actividad 4 · API Gateway y protección de la API

### 6.1 HTTP API o REST API

| | HTTP API (elegida) | REST API |
|---|---|---|
| Costo y latencia | Hasta ~70 % más barata y con menor latencia | Mayor |
| Throttling | Por etapa y por ruta (velocidad y ráfaga) | Por etapa, método y *usage plans* con API keys por cliente |
| Autorización | JWT nativo, IAM, Lambda | Cognito, IAM, Lambda, API keys |
| Extras | CORS simple, proxy HTTP | WAF, caché, transformación de solicitudes, validación de modelos |

**Justificación:** PetCare necesita un proxy hacia Django con limitación de solicitudes. HTTP API lo resuelve con menos costo y configuración. Si se necesitara AWS WAF integrado o cuotas por cliente con API keys, se usaría REST API.

### 6.2 Configuración (E13–E15)

- **Ruta:** `ANY /api/{proxy+}`. La integración es HTTP proxy con `ANY https://petcare-sfvet.duckdns.org/api/{proxy}`.
- **Mapeo de parámetros de la integración:** sobrescribe `header.x-petcare-gateway` con un secreto compartido. `clinic/middleware.py` rechaza con **403** toda solicitud a `/api/` que llegue a la EC2 sin esa cabecera. Así **no se puede saltar el rate limit** llamando directo a la IP del backend (E17).
- **Throttling de la etapa `$default`:** **2 solicitudes por segundo y ráfaga de 5**.
- **Defensa en profundidad:** el login de Django además limita a 10 intentos por minuto (`ScopedRateThrottle`).

### 6.3 Prueba (E16)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\rate-limit-test.ps1 -Url https://<ID>.execute-api.us-east-1.amazonaws.com/api/salud/ -Total 30
```

Resultado esperado: las primeras solicitudes (ráfaga) responden **200** y el resto **429 Too Many Requests**, generadas por API Gateway sin llegar a la EC2. Los límites son objetivos de *token bucket*, por lo que el corte exacto puede variar.

### 6.4 Conceptos

| Control | Pregunta que responde | En PetCare |
|---|---|---|
| Autenticación | ¿Quién eres? | JWT emitido tras usuario y contraseña (Argon2) |
| Autorización | ¿Qué puedes hacer? | `IsAdminUser` + `RolePermission` (Recepción no gestiona profesionales ni servicios) |
| Rate limiting | ¿Cuántas solicitudes por unidad de tiempo? | Throttling de API Gateway (2/s, ráfaga 5) + 10 logins por minuto |
| Protección DDoS | ¿Puede el servicio resistir un volumen masivo y distribuido? | AWS Shield Standard (automático) protege API Gateway y la red de AWS. El rate limit **no** reemplaza la protección DDoS |

- **AWS Shield:** Standard es gratuito y automático contra ataques de red y transporte (capas 3 y 4, por ejemplo SYN flood o reflexión UDP). Advanced es pagado, con protección en la capa 7, equipo de respuesta y protección de costos.
- **AWS WAF:** firewall de aplicación (capa 7) con reglas sobre IP, geografía, SQLi, XSS y tasa por IP. Se asocia a REST API, CloudFront o ALB. No se desplegó; se usaría con REST API para bloquear patrones de ataque antes de llegar a Django.

---

## 7. Actividad 5 · PostgreSQL en Amazon RDS

| Requisito | Configuración | Evidencia |
|---|---|---|
| Separación | La base está en `petcare-db` (RDS) y el PostgreSQL local de la EC2 quedó deshabilitado | E18, E21 |
| Conectividad | Django con `PGHOST=<endpoint>`, usuario `petcare_app` | E21 |
| Security Group | `petcare-rds-sg`: entrada **5432 solo desde el SG de la EC2 backend**; acceso público **No** | E20 |
| Cifrado en reposo | Habilitado al crear la instancia (KMS `aws/rds`). Los snapshots heredan el cifrado | E19 |
| TLS en tránsito | `PGSSLMODE=verify-full` + CA `global-bundle.pem` de AWS: cifra y valida el certificado y el nombre del servidor | E21 |
| Credenciales | Usuario maestro solo para administrar (su clave no se guarda). La app usa `petcare_app`, dueño solo de la base `petcare`, con clave aleatoria de 32 bytes en `/etc/petcare/petcare.env` (permisos 640, root:petcare), fuera del repositorio | E21 |

El cifrado en reposo no se puede activar en una instancia existente. Para hacerlo habría que crear un snapshot, copiarlo cifrado y restaurarlo. Por eso se planificó desde la creación. La migración de datos la hace `deploy/migrate-to-rds.sh` (`pg_dump` → `psql` sobre TLS).

**Alternativa:** guardar la credencial en AWS Secrets Manager con rotación automática y leerla con el rol IAM. No se usó por las restricciones del laboratorio, pero sería la opción en producción.

---

## 8. Actividad 6 · Seguridad del bucket S3

| Control | Configuración | Evidencia |
|---|---|---|
| Bucket | `<BUCKET>`: `static/` (CSS, imágenes, fuentes), `media/` (adjuntos clínicos), `reportes/` (PDF/Excel) | E24 |
| Cifrado en reposo | SSE-S3 (AES-256) por defecto en el bucket y explícito en cada objeto (`ServerSideEncryption: AES256`) | E22 |
| Block Public Access | Los 4 bloqueos activados: ningún objeto es público | E23 |
| Permisos | La EC2 usa el rol IAM `LabInstanceProfile` (credenciales temporales rotadas por STS). No hay claves de acceso en el código ni en el servidor | E26 |
| Distribución controlada | Los **estáticos** los lee Django con el rol y Nginx los cachea (`/static/…`). Los **adjuntos y reportes** se entregan con **URL prefirmadas** de 2 a 5 minutos, después de verificar la sesión y el rol | E25 |
| Versionado | Habilitado: guarda versiones anteriores ante sobrescritura o borrado accidental | E22 |

**Cifrado, control de acceso y versionado:**
- **Cifrado:** protege la *confidencialidad* de los datos guardados en disco.
- **Control de acceso** (IAM, políticas, Block Public Access): decide *quién* puede leer o escribir.
- **Versionado:** protege la *disponibilidad e integridad histórica*, porque permite recuperar versiones anteriores.

Un bucket cifrado pero público sigue expuesto. Uno privado sin versionado puede perder datos por un borrado.

---

## 9. Actividad 7 · Monitoreo con Amazon CloudWatch

- **Métricas de la EC2 backend (E27):** `CPUUtilization`, `NetworkIn` y `NetworkOut`, `DiskReadOps`, `StatusCheckFailed` (y `CPUCreditBalance` en instancias T). En RDS: `CPUUtilization`, `FreeStorageSpace`, `DatabaseConnections` y `FreeableMemory`.
- **Alarma (E28):** `petcare-backend-cpu-alta` se activa cuando `CPUUtilization` es mayor que 70 % (promedio) durante 2 periodos de 5 minutos. Su acción es avisar al tema SNS `petcare-alertas` (correo confirmado, E29).
- **Logs:** la Lambda de respaldo escribe en CloudWatch Logs (`/aws/lambda/petcare-rds-snapshot`). Gunicorn y Nginx registran en `journalctl` en la EC2.

| | Métricas | Logs | Alarmas |
|---|---|---|---|
| Qué son | Series numéricas en el tiempo (CPU %, conexiones) | Eventos de texto con detalle (una solicitud, un error) | Reglas sobre una métrica que cambian de estado (OK, ALARMA, DATOS INSUFICIENTES) |
| Para qué | Ver tendencias y capacidad | Investigar *qué* pasó y *por qué* | Avisar o actuar automáticamente (SNS, escalado) |

---

## 10. Actividad 8 · Respaldos y recuperación

- **Respaldos automáticos (E30):** retención de 7 días, con ventana diaria y registros de transacciones cada 5 minutos. Permiten la **restauración a un punto en el tiempo (PITR)** a cualquier segundo dentro de la retención.
- **Snapshot manual (E31):** `petcare-db-snapshot-manual`. Se conserva hasta que se borra, aunque se elimine la instancia.

| | Respaldo automático | Snapshot manual |
|---|---|---|
| Creación | RDS, diario, en la ventana configurada | A pedido (consola, CLI o Lambda) |
| Retención | 1 a 35 días; se borra con la instancia (salvo que se retenga) | Indefinida, hasta eliminarlo |
| Recuperación | Punto en el tiempo (PITR) | Estado exacto del momento del snapshot |

**Alternativas de recuperación:**
1. Restaurar a un punto en el tiempo (nueva instancia).
2. Restaurar desde un snapshot (nueva instancia).
3. Copiar un snapshot a otra región o cuenta para recuperación ante desastres.
4. Exportar un snapshot a S3 (Parquet) para análisis.

En todos los casos se crea una **nueva** instancia y se cambia el `PGHOST` de Django.

**Respaldo cada 7 horas (ampliación, E32):** RDS no permite esa frecuencia nativa. Se implementó `deploy/lambda/rds_snapshot.py`, que se ejecuta con una regla de **Amazon EventBridge** `rate(7 hours)`. La función:
- Crea el snapshot `petcare-7h-AAAAMMDD-HHMM`, que queda cifrado.
- Conserva los 8 más recientes y borra los anteriores.
- Avisa por SNS.
- Registra su ejecución en CloudWatch Logs.

Esto complementa el PITR nativo, no lo reemplaza.

---

## 11. Uso de inteligencia artificial

| # | Recomendación de la IA | Contraste con documentación oficial | Decisión |
|---|---|---|---|
| 1 | Usar Argon2id como hasher de contraseñas | [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) recomienda Argon2id; la [documentación de Django](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/) lo soporta con `argon2-cffi` | **Aplicada.** PBKDF2 se mantiene como respaldo para migrar hashes existentes |
| 2 | Guardar el JWT en `localStorage` para mantener la sesión | [OWASP HTML5 Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html) advierte que cualquier XSS puede leer `localStorage` | **Descartada.** Access en memoria, refresh en `sessionStorage` con rotación y lista negra, y CSP estricta |
| 3 | Hacer público el bucket S3 para servir CSS e imágenes | [S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html) recomienda mantenerlo activo salvo necesidad explícita | **Descartada.** Bucket privado, lectura con rol IAM y URL prefirmadas |
| 4 | Limitar solicitudes solo en Django (DRF throttling) | [Throttling de HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html): API Gateway rechaza antes de llegar al servidor | **Aplicada en ambos niveles.** API Gateway (borde) + login en Django, con una cabecera secreta para impedir el acceso directo |
| 5 | Activar el cifrado de RDS después de crearla | [Cifrado de RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.Encryption.html): no se puede activar en una instancia existente | **Corregida.** Se creó cifrada desde el inicio |

El registro completo de solicitudes a la IA está en `prompts_ia.md`.

---

## 12. Preparación para las preguntas orales

- **¿Por qué SAST y DAST juntos?** Detectan cosas distintas: código frente a despliegue. En PetCare, ZAP revisa las cabeceras de Nginx y la CSP, que SonarQube no ve.
- **¿Por qué Argon2 y no SHA-256?** SHA-256 es rápido y no usa memoria. Argon2id es lento y usa 100 MiB por intento, lo que encarece la fuerza bruta con GPU.
- **¿Qué pasa si alguien llama directo a la EC2?** Recibe 403 porque falta la cabecera secreta que solo agrega API Gateway (E17).
- **¿El rate limit protege contra DDoS?** Solo en parte: limita la tasa que llega al backend, pero un DDoS de red se mitiga con Shield, y uno de capa 7 con WAF y CloudFront.
- **¿Cómo se protege la contraseña de RDS?** Hay un usuario de aplicación con privilegios mínimos, su clave está en un archivo legible solo por el servicio y la conexión usa TLS `verify-full`. La alternativa es Secrets Manager.
- **¿Qué se pierde si se borra la instancia RDS?** Los respaldos automáticos, salvo que se retengan. Los snapshots manuales se conservan.
