# Registro de apoyo de IA

Proyecto 1 de la Evaluación 3 de Desarrollo Backend: PetCare (Veterinaria San Francisco).

## Herramientas utilizadas

| Herramienta | Uso principal |
| --- | --- |
| Codex | Desarrollo local: modelos, reglas de negocio, plantillas, API y pruebas |
| Claude Code | Revisión contra la pauta, Django Admin y preparación del despliegue en AWS EC2 |

Las decisiones de alcance, el nombre, el logo y la validación final de cada flujo estuvieron a cargo del estudiante. El código generado se revisó y se probó con la suite de pruebas de Django (`manage.py test`).

## Etapa 1: análisis y modelo de datos (Codex)

| Solicitud del estudiante | Apoyo aplicado | Resultado en el repositorio |
| --- | --- | --- |
| «el proyecto que me ha tocado realizar es el proyecto 1 el cual pertenece a una veterinaria» | Lectura de la pauta y del enunciado. Diseño de entidades y relaciones | `clinic/models.py` y `clinic/migrations/0001_initial.py` |
| «si un sistema de inventario pero no una caja como tal» | Catálogo de insumos, historial de entradas y salidas y alerta de stock mínimo | `Insumo`, `Movimiento` y la alerta en el inicio |

## Etapa 2: lógica de negocio, interfaz y seguridad (Codex)

| Solicitud del estudiante | Apoyo aplicado | Resultado en el repositorio |
| --- | --- | --- |
| «todo lo que sea de administración la idea es que sea en un template» | Panel de gestión con HTML y formularios, sesiones, y roles de Administración y Jefatura | `clinic/views.py` y `clinic/templates/clinic/` |
| (implícito en el caso) Evitar el solapamiento de horas | Validación de cruces por profesional y mascota, y citas solo dentro de bloques de disponibilidad | `clinic/services.py` |
| (implícito en el caso) Seguimiento de vacunas | Recordatorios con anticipación, repetición periódica y reintento si falla el envío | `clinic/management/commands/enviar_recordatorios.py` |
| «veremos el diseño más adelante» y «Este logo y nombre pongamos a la veterinaria» | Interfaz provisional con el nombre Veterinaria San Francisco y el logo aportado | `clinic/static/clinic/` |

## Etapa 3: pruebas locales (Codex)

| Solicitud del estudiante | Apoyo aplicado | Resultado en el repositorio |
| --- | --- | --- |
| «primero hagamoslo en local y luego lo subimos» | Configuración local de PostgreSQL y pruebas de los flujos de la clínica | `README.md` y `clinic/tests.py` |

## Etapa 4: revisión contra la pauta y Django Admin (Claude Code)

| Solicitud del estudiante | Apoyo aplicado | Resultado en el repositorio |
| --- | --- | --- |
| «Necesito que analices la carpeta [...] y que verifiques que cumpla con mayoría de cosas que piden en los documentos» | Comparación del proyecto con la rúbrica. Se detectó que faltaba Django Admin (criterio 2), que las cookies seguras impedían iniciar sesión por HTTP en EC2 y que faltaban los archivos de despliegue | Diagnóstico entregado al estudiante |
| «Sí, aplícalos» | Admin personalizado con los 9 modelos, filtros, búsquedas, inlines, acciones y plantilla con la marca. Las reglas de negocio se extrajeron a `validate_rules` para que el Admin aplique las mismas validaciones | `clinic/admin.py`, `clinic/templates/admin/base_site.html`, `clinic/static/clinic/admin.css` y `clinic/services.py` |
| (misma solicitud) | Nueva variable `PETCARE_HTTPS`, cookies de sesión `HttpOnly` y expiración de la sesión | `petcare/settings.py` |
| (misma solicitud) | Prueba automática del Admin: acceso por rol, rechazo de citas cruzadas y control de stock | `clinic/tests.py` |

| «podrías darme opciones de diseño siguiendo el estilo del logo? [...] trata de que sea lo más original posible» | Tres propuestas visuales basadas en el logo (Letrero, Carnet de vacunas y Huellas) para que el estudiante eligiera | Propuestas comparadas con maquetas |
| «El C de huellas lo veo bonito» | Rediseño del panel y del Admin con la propuesta Huellas: menú lateral verde bosque, tipografías Baloo 2 y Nunito, y un camino de huellas para la agenda y la ficha clínica | `clinic/static/clinic/panel.css`, `clinic/templates/clinic/` y `clinic/static/clinic/admin.css` |

## Etapa 5: despliegue en AWS EC2 (Claude Code)

| Solicitud del estudiante | Apoyo aplicado | Resultado en el repositorio |
| --- | --- | --- |
| «Todo está en local y aún no lo paso a aws, hoy debo realizar eso» | Script de instalación idempotente con PostgreSQL, Gunicorn, Nginx y systemd, timer de recordatorios y detección automática de la IP pública para `ALLOWED_HOSTS` | `deploy/` y la sección de despliegue del `README.md` |

| «Sí, créalo» (datos de demostración para la defensa) | Comando que carga tutores, mascotas, profesionales, dos semanas de agenda, fichas clínicas, recordatorios e inventario usando las mismas reglas de negocio. No duplica datos si la base ya tiene registros | `clinic/management/commands/datos_demo.py` |

| «me gustaría agregar un sistema en el que para el inventario puedan pedir una orden para comprar y que eso me lleve a transbank» y «solo quiero que sea simulado» | Órdenes de compra con ítems, pago con Webpay Plus en el ambiente de integración de Transbank y entrada automática al inventario si el pago se aprueba. Se probó el flujo completo con la tarjeta de prueba de Transbank | `clinic/webpay.py`, `clinic/purchases.py`, `clinic/purchase_views.py`, `clinic/templates/clinic/purchase_*.html` y `clinic/migrations/0002_ordenes_compra.py` |

| «Hay alguna forma de optimizar la pagina? siento que va bastante lenta» | Se midieron los tiempos en el sitio público: Django respondía rápido y el problema eran los bytes sobre una conexión lenta hacia us-east-1. Logo de 150 KB a 15 KB (WebP), compresión gzip en Nginx, estáticos versionados con caché de un año, fuentes sin bloquear el dibujado y conexiones persistentes a PostgreSQL | `clinic/static/clinic/logo.webp`, `deploy/nginx-*.conf`, `petcare/settings.py` y `clinic/templates/` |

| «podríamos crear alguna cuenta que restringa unas cuantas opciones como crear y eliminar profesionales quizá, hacer pedidos» y «que no eliminar si no dejar como inactivo» | Rol Recepción (grupo de Django) sin gestión de profesionales, compras ni Django Admin, aplicado en el panel, la API y el Admin. Selección de rol al crear cuentas. Profesionales con estado activo/inactivo en vez de eliminación, con bloqueo si tienen citas por delante | `clinic/roles.py`, `clinic/views.py`, `clinic/services.py`, `clinic/admin.py`, `clinic/api.py` y `clinic/migrations/0003_profesional_activo_y_recepcion.py` |

## Criterio propio aplicado

- Se descartó exponer PostgreSQL a Internet. La base solo escucha en `127.0.0.1` dentro de la instancia.
- Las claves (`SECRET_KEY` y la contraseña de la base) se generan en el servidor y no se suben al repositorio.
- Los cambios propuestos por la IA se incorporaron después de pasar las pruebas automáticas.
