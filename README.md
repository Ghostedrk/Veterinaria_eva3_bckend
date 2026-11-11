# Veterinaria San Francisco

**Aplicación desplegada en AWS EC2:** [http://44.213.33.107/](http://44.213.33.107/) · Django Admin: [http://44.213.33.107/admin/](http://44.213.33.107/admin/)

Panel interno para el Proyecto 1 de la Evaluación 3 de Desarrollo Backend, cuyo caso académico se llama PetCare. La interfaz lleva el nombre y el logo entregados por el estudiante. El diseño "Huellas" toma el verde y el café del logo, usa un menú lateral y muestra la agenda y la ficha clínica de cada mascota como un camino de huellas. Se adapta a pantallas de celular.

Stack: Django 5.2, Django REST Framework, PostgreSQL, plantillas HTML/CSS, Django Admin, y Gunicorn con Nginx en AWS EC2.

| Requerimiento del caso | Dónde está |
| --- | --- |
| CRUD de tutores y mascotas | Panel (`/gestion/tutores/`, `/gestion/mascotas/`), API (`/api/`) y Admin |
| Agenda con disponibilidad por profesional | `/agenda/`, bloques de disponibilidad y validación de cruces en `clinic/services.py` |
| Ficha clínica (diagnóstico, tratamiento, receta, exámenes) | Atenciones, visibles en el perfil de cada mascota |
| Recordatorios de vacunación y controles | Modelo `Recordatorio` y comando `enviar_recordatorios` (timer de systemd en EC2) |
| Seguridad y sesiones | Login de Django, roles Jefatura y Administración, CSRF, y API restringida a cuentas del personal |

## Requisitos

- Python 3.10 o superior y PostgreSQL 14 o superior.
- Django 5.2, Django REST Framework y psycopg se instalan desde `requirements.txt`.

## Ejecutar en Windows

Desde PowerShell, abre la carpeta que contiene `manage.py`:

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

En PostgreSQL, ejecuta estas sentencias como administrador. Usa una contraseña local propia.

```sql
CREATE ROLE petcare LOGIN PASSWORD 'reemplazar-por-una-clave-local';
CREATE DATABASE petcare OWNER petcare;
```

Configura la conexión y prepara el panel:

```powershell
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '5432'
$env:PGDATABASE = 'petcare'
$env:PGUSER = 'petcare'
$env:PGPASSWORD = 'reemplazar-por-una-clave-local'
& .\.venv\Scripts\python.exe manage.py migrate
& .\.venv\Scripts\python.exe manage.py createsuperuser
& .\.venv\Scripts\python.exe manage.py runserver
```

Abre [el panel local](http://127.0.0.1:8000/) e ingresa con la cuenta creada. El comando `createsuperuser` provisiona la primera cuenta de **Jefatura**. En **Cuentas**, Jefatura puede crear, activar y desactivar cuentas de **Administración**. Ambos roles pueden gestionar las operaciones de la clínica.

Para una prueba rápida de la interfaz también puedes usar `$env:PETCARE_DB = 'sqlite'` antes de migrar. Usa PostgreSQL para la evaluación y ejecuta `Remove-Item Env:PETCARE_DB` si activaste SQLite y quieres volver a PostgreSQL.

Si Windows bloquea la extensión binaria de psycopg, puedes usar la variante Python con la biblioteca `libpq` de tu instalación de PostgreSQL. En PowerShell, ajusta la ruta de la versión instalada:

```powershell
$env:PATH = 'C:\Program Files\PostgreSQL\18\bin;' + $env:PATH
$env:PSYCOPG_IMPL = 'python'
```

## Flujos del panel

1. En **Tutores** y **Mascotas**, crea un tutor con correo y vincula la mascota.
2. En **Agenda**, registra un profesional, crea un bloque de disponibilidad y agenda una cita dentro del bloque. El calendario semanal se puede filtrar por profesional. Si dos citas se cruzan para el mismo profesional o mascota, el sistema rechaza el cambio.
3. Desde el perfil de la mascota, registra una atención. La ficha agrupa diagnósticos, tratamientos, recetas y exámenes.
4. Programa un recordatorio de vacunación o control. El sistema calcula cuándo enviarlo a partir de la fecha objetivo y la anticipación. Si indicas una frecuencia en días, cada envío exitoso programa el siguiente.
5. En **Inventario**, crea un insumo y registra entradas y salidas. El historial conserva usuario, fecha y motivo. El inicio muestra insumos con stock igual o inferior al mínimo.

## Recordatorios

En desarrollo los mensajes se imprimen en la consola. Usa correos ficticios durante las pruebas. En otra terminal con las mismas variables de conexión:

```powershell
& .\.venv\Scripts\python.exe manage.py enviar_recordatorios --cada 60
```

Para una sola ejecución, omite `--cada 60`. Cada ciclo procesa los avisos pendientes y conserva los fallidos para reintento. Un envío de correo y el registro en la base son operaciones separadas. Si el proceso se interrumpe justo después de que SMTP acepta un mensaje, el aviso puede repetirse en el siguiente ciclo.

## API y pruebas

La [API navegable](http://127.0.0.1:8000/api/) reutiliza la sesión del panel. Para escrituras desde un cliente que use esa sesión, envía la cookie de sesión y el token CSRF. Las rutas ofrecen listados paginados y búsqueda mediante `?search=`. Los movimientos admiten lectura y creación para conservar el historial.

```powershell
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py test
```

Django necesita una base de pruebas temporal. Usa un rol local con permiso `CREATEDB` para ejecutar la suite sobre PostgreSQL, o ejecuta las pruebas con SQLite.

## Django Admin

El panel de Django Admin está en `/admin/` y usa las mismas cuentas del panel clínico. Tiene el nombre y el logo de la veterinaria (`clinic/templates/admin/base_site.html` y `clinic/static/clinic/admin.css`).

- Registra los 9 modelos del dominio con listados, búsquedas, filtros y navegación por fecha.
- Tutores y mascotas muestran en línea sus mascotas, su ficha clínica y sus recordatorios.
- Las citas tienen acciones masivas para marcarlas como atendidas o cancelarlas.
- Los insumos tienen un filtro de stock bajo el mínimo.
- El Admin aplica las mismas reglas que el panel y la API (`clinic/services.py`): rechaza citas fuera de disponibilidad o que se cruzan, rechaza salidas sin stock y deja en solo lectura los recordatorios enviados y los movimientos de inventario.
- **Jefatura** (superusuario) también administra usuarios y grupos. **Administración** gestiona solo los modelos de la clínica.

## Despliegue en AWS EC2

**IP pública (AWS EC2, IP elástica):** [http://44.213.33.107/](http://44.213.33.107/) · Django Admin: [http://44.213.33.107/admin/](http://44.213.33.107/admin/)

Arquitectura en una única instancia EC2:

```
Navegador ──HTTP:80──▶ Nginx ──▶ Gunicorn (127.0.0.1:8000) ──▶ Django/DRF ──▶ PostgreSQL (127.0.0.1:5432)
                        └── /static/ (archivos estáticos)      systemd timer ──▶ enviar_recordatorios (cada 15 min)
```

1. En AWS Academy, inicia el Learner Lab y lanza una instancia **Ubuntu Server 24.04**, tipo `t3.small` o `t2.micro`, con el par de llaves `vockey`.
2. En el grupo de seguridad, abre la entrada **SSH (22)** solo para tu IP y **HTTP (80)** para `0.0.0.0/0`. PostgreSQL no se expone.
3. Conéctate por SSH e instala:

   ```bash
   sudo apt-get update && sudo apt-get install -y git
   sudo git clone https://github.com/Ghostedrk/Veterinaria_eva3_bckend.git /opt/petcare
   sudo bash /opt/petcare/deploy/setup.sh
   sudo petcare-manage createsuperuser
   ```

4. Abre `http://44.213.33.107/` en el navegador.

`setup.sh` se puede volver a ejecutar sin perder datos. Instala PostgreSQL, Nginx y Python, crea la base y su usuario con una clave aleatoria, y genera `/etc/petcare/petcare.env` con `PETCARE_DEBUG=0` y una `SECRET_KEY` propia. Después aplica las migraciones, ejecuta `collectstatic` y deja los servicios activos al arrancar. La IP y el DNS públicos se agregan solos a `ALLOWED_HOSTS` en cada inicio, porque en AWS Academy la IP cambia al reiniciar el laboratorio.

Operación habitual:

| Acción | Comando |
| --- | --- |
| Actualizar desde GitHub | `sudo bash /opt/petcare/deploy/update.sh` |
| Cargar datos de demostración (solo si la base no tiene tutores) | `sudo petcare-manage datos_demo` |
| Ver registros de la app | `sudo journalctl -u petcare -n 50` |
| Ver recordatorios enviados | `sudo journalctl -u petcare-reminders -n 50` |
| Enviar recordatorios ahora | `sudo petcare-manage enviar_recordatorios` |
| Consola de PostgreSQL | `sudo -u postgres psql petcare` |

### HTTPS (opcional)

Sin dominio, el sitio funciona por HTTP en la IP pública (`PETCARE_HTTPS=0`). Para activar HTTPS con un certificado gratuito de Let's Encrypt:

1. Asocia una IP elástica a la instancia para que la IP no cambie al reiniciar el laboratorio.
2. Crea un subdominio gratuito en [DuckDNS](https://www.duckdns.org) que apunte a esa IP.
3. Abre el puerto **443** en el grupo de seguridad.
4. Ejecuta el script con tu subdominio y tu correo:

   ```bash
   sudo bash /opt/petcare/deploy/enable-https.sh petcare-sf.duckdns.org correo@ejemplo.com
   ```

El script verifica que el dominio apunte a la instancia, obtiene el certificado y activa las cookies seguras y la redirección a HTTPS en Django. Si después alguien entra por `http://IP`, se le redirige al dominio con HTTPS. El certificado se renueva solo y `update.sh` conserva esta configuración.

### Correo de recordatorios

En el servidor los recordatorios se escriben en el registro del sistema. Para enviarlos por correo real hay que configurar las variables `PETCARE_SMTP_*` y quitar `PETCARE_EMAIL_BACKEND`.

