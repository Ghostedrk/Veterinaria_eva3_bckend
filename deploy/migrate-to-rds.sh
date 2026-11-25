#!/usr/bin/env bash
# Traslada la base de datos de PostgreSQL local (en la EC2) a Amazon RDS.
#
# Uso: sudo bash /opt/petcare/deploy/migrate-to-rds.sh <endpoint-rds> [usuario-maestro]
#
# 1. Pide la contraseña del usuario maestro de RDS (no se guarda en ninguna parte).
# 2. Crea un usuario de aplicación con privilegios mínimos (petcare_app) y clave aleatoria.
# 3. Copia los datos con pg_dump/psql usando TLS verificado (sslmode=verify-full).
# 4. Apunta Django a RDS y apaga el PostgreSQL local.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
require_root

ENDPOINT=${1:-}
MASTER=${2:-petcare_admin}
DB=petcare
APP_USER=petcare_app
CA=/etc/petcare/rds-ca.pem

if [[ -z "$ENDPOINT" ]]; then
    echo "Uso: sudo bash $0 <endpoint-rds> [usuario-maestro]" >&2
    exit 1
fi

echo "==> CA de Amazon RDS para TLS"
curl -sf -o "$CA" https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
chmod 644 "$CA"

echo "==> Probando la conexión TLS a $ENDPOINT:5432"
read -rsp "Contraseña del usuario maestro ($MASTER): " MASTER_PW
echo
export PGSSLMODE=verify-full PGSSLROOTCERT="$CA"
master() { PGPASSWORD="$MASTER_PW" psql "host=$ENDPOINT port=5432 dbname=$DB user=$MASTER" -v ON_ERROR_STOP=1 -q "$@"; }
master -tAc "SELECT 'TLS: ' || ssl::text || ' · ' || version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"

echo "==> Usuario de aplicación con privilegios mínimos ($APP_USER)"
APP_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
if master -tAc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1; then
    master -c "ALTER ROLE $APP_USER WITH LOGIN PASSWORD '$APP_PW'"
else
    master -c "CREATE ROLE $APP_USER WITH LOGIN PASSWORD '$APP_PW'"
fi
master -c "GRANT $APP_USER TO CURRENT_USER" 2>/dev/null || true
master -c "ALTER DATABASE $DB OWNER TO $APP_USER"
master -c "ALTER SCHEMA public OWNER TO $APP_USER"
master -c "REVOKE ALL ON DATABASE $DB FROM PUBLIC"
unset MASTER_PW

app() { PGPASSWORD="$APP_PW" psql "host=$ENDPOINT port=5432 dbname=$DB user=$APP_USER" -v ON_ERROR_STOP=1 -q "$@"; }
TABLES=$(app -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")

set -a
. "$ENV_FILE"
set +a
if { [[ "$PGHOST" = "127.0.0.1" ]] || [[ "$PGHOST" = "localhost" ]]; } && [[ "$TABLES" = "0" ]]; then
    echo "==> Copiando datos desde el PostgreSQL local"
    DUMP=$(mktemp /tmp/petcare-XXXXXX.sql)
    sudo -u postgres pg_dump --no-owner --no-privileges "$PGDATABASE" > "$DUMP"
    app -f "$DUMP" > /dev/null
    shred -u "$DUMP" 2>/dev/null || rm -f "$DUMP"
else
    echo "==> RDS ya tiene $TABLES tablas o la app ya no usa la base local: no se copian datos."
fi

echo "==> Apuntando Django a RDS"
set_env PGHOST "$ENDPOINT"
set_env PGPORT 5432
set_env PGDATABASE "$DB"
set_env PGUSER "$APP_USER"
set_env PGPASSWORD "$APP_PW"
set_env PGSSLMODE verify-full
set_env PGSSLROOTCERT "$CA"
unset APP_PW

petcare-manage migrate --noinput
systemctl restart petcare

echo "==> Apagando PostgreSQL local (los datos quedan solo en RDS)"
systemctl disable --now postgresql 2>/dev/null || true

sleep 2
petcare-manage shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute('SELECT inet_server_addr(), current_user, ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()')
    print('Django conectado a RDS:', c.fetchone())
from clinic.models import Tutor, Mascota, Cita
print('Registros:', Tutor.objects.count(), 'tutores,', Mascota.objects.count(), 'mascotas,', Cita.objects.count(), 'citas')
"
echo "Listo. La credencial de $APP_USER quedó solo en $ENV_FILE (permisos 640, root:petcare)."
