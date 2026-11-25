#!/usr/bin/env bash
# Protege la API para que solo responda a través de Amazon API Gateway y autoriza el frontend (CORS).
#
# Uso: sudo bash /opt/petcare/deploy/enable-gateway.sh http://<IP-del-frontend>
#
# Genera (una sola vez) un secreto compartido. API Gateway debe agregarlo como cabecera
# "x-petcare-gateway" en la integración; sin ella, /api/ responde 403.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
require_root

ORIGIN=${1:-}
if [[ -z "$ORIGIN" ]]; then
    echo "Uso: sudo bash $0 http://<IP-del-frontend>" >&2
    exit 1
fi

SECRET=$(grep -E '^PETCARE_GATEWAY_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)
if [[ -z "$SECRET" ]]; then
    SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
    set_env PETCARE_GATEWAY_SECRET "$SECRET"
fi
set_env PETCARE_CORS_ORIGINS "${ORIGIN%/}"
systemctl restart petcare
sleep 2

echo
echo "Directo a la EC2 (sin la cabecera): $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/api/salud/) (esperado 403)"
echo "Con la cabecera de API Gateway:    $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' -H 'X-Forwarded-Proto: https' -H "X-Petcare-Gateway: $SECRET" http://127.0.0.1:8000/api/salud/) (esperado 200)"
echo
echo "Configura en API Gateway (Integración → Mapeo de parámetros → Agregar):"
echo "    Modificar: header.x-petcare-gateway   Acción: Sobrescribir   Valor: $SECRET"
echo "No compartas este valor: es lo que impide saltarse el rate limit."
