#!/usr/bin/env bash
# Instala o actualiza PetCare en una instancia EC2 Ubuntu (22.04 o 24.04).
# Uso: sudo git clone <repo> /opt/petcare && sudo bash /opt/petcare/deploy/setup.sh
# Es idempotente: se puede volver a ejecutar sin perder datos ni claves.
set -euo pipefail

APP_DIR=/opt/petcare
ENV_DIR=/etc/petcare
ENV_FILE=$ENV_DIR/petcare.env

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecuta este script con sudo." >&2
    exit 1
fi
if [ ! -f "$APP_DIR/manage.py" ]; then
    echo "No se encontró $APP_DIR/manage.py. Clona el repositorio en $APP_DIR." >&2
    exit 1
fi

echo "==> Paquetes del sistema"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    python3-venv python3-pip postgresql nginx git curl

echo "==> Usuario del servicio"
id petcare >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin petcare
chown -R petcare:petcare "$APP_DIR"
git config --system --add safe.directory "$APP_DIR" 2>/dev/null || true

echo "==> Variables de entorno ($ENV_FILE)"
mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    DB_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
    cat > "$ENV_FILE" <<EOF
# Configuración de producción de PetCare. No subir este archivo al repositorio.
PETCARE_DEBUG=0
PETCARE_SECRET_KEY=$SECRET
# Sin certificado TLS se accede por http://IP-publica; con HTTPS cambia a 1.
PETCARE_HTTPS=0
# Hosts adicionales separados por coma (la IP y el DNS público se detectan solos).
PETCARE_EXTRA_HOSTS=
# Los recordatorios se registran en el journal: journalctl -u petcare-reminders
PETCARE_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
PGHOST=127.0.0.1
PGPORT=5432
PGDATABASE=petcare
PGUSER=petcare
PGPASSWORD=$DB_PASS
EOF
fi
chown root:petcare "$ENV_FILE"
chmod 640 "$ENV_FILE"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

echo "==> PostgreSQL"
systemctl enable --now postgresql
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PGUSER'" | grep -q 1; then
    sudo -u postgres psql -q -c "ALTER ROLE $PGUSER WITH LOGIN PASSWORD '$PGPASSWORD'"
else
    sudo -u postgres psql -q -c "CREATE ROLE $PGUSER LOGIN PASSWORD '$PGPASSWORD'"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PGDATABASE'" | grep -q 1; then
    sudo -u postgres createdb -O "$PGUSER" "$PGDATABASE"
fi

echo "==> Entorno virtual y dependencias"
[ -x "$APP_DIR/.venv/bin/python" ] || sudo -u petcare python3 -m venv "$APP_DIR/.venv"
sudo -u petcare "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u petcare "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Comando petcare-manage"
install -m 755 "$APP_DIR/deploy/petcare-manage" /usr/local/bin/petcare-manage

echo "==> Migraciones y archivos estáticos"
bash "$APP_DIR/deploy/petcare-hosts.sh"
petcare-manage migrate --noinput
petcare-manage collectstatic --noinput -v 0
petcare-manage check

echo "==> Servicios systemd"
install -m 644 "$APP_DIR"/deploy/petcare.service /etc/systemd/system/petcare.service
install -m 644 "$APP_DIR"/deploy/petcare-reminders.service /etc/systemd/system/petcare-reminders.service
install -m 644 "$APP_DIR"/deploy/petcare-reminders.timer /etc/systemd/system/petcare-reminders.timer
systemctl daemon-reload
systemctl enable petcare petcare-reminders.timer
systemctl restart petcare
systemctl start petcare-reminders.timer

echo "==> Nginx"
mkdir -p /var/www/certbot
if [ -f "$ENV_DIR/https-domain" ]; then
    # HTTPS ya fue activado con enable-https.sh: se conserva al actualizar.
    DOMAIN=$(cat "$ENV_DIR/https-domain")
    sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx-petcare-https.conf" > /etc/nginx/sites-available/petcare
else
    install -m 644 "$APP_DIR/deploy/nginx-petcare.conf" /etc/nginx/sites-available/petcare
fi
ln -sf /etc/nginx/sites-available/petcare /etc/nginx/sites-enabled/petcare
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

sleep 2
if curl -sf -o /dev/null -H "Host: localhost" http://127.0.0.1/ingresar/; then
    echo "==> PetCare responde correctamente."
else
    echo "!! PetCare no respondió. Revisa: sudo journalctl -u petcare -n 50" >&2
fi
. /run/petcare-hosts.env
echo
echo "Hosts permitidos: $PETCARE_HOSTS"
echo "Si es la primera instalación, crea la cuenta de Jefatura con:"
echo "    sudo petcare-manage createsuperuser"
