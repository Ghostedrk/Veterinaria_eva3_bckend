#!/usr/bin/env bash
# Activa HTTPS con un certificado gratuito de Let's Encrypt.
# Requisitos: un dominio (por ejemplo, DuckDNS) que apunte a la IP elástica
# de la instancia y el puerto 443 abierto en el grupo de seguridad.
# Uso: sudo bash /opt/petcare/deploy/enable-https.sh petcare-sf.duckdns.org correo@ejemplo.com
# Al ejecutarlo se aceptan los términos de servicio de Let's Encrypt.
set -euo pipefail

DOMAIN=${1:-}
EMAIL=${2:-}
APP_DIR=/opt/petcare
ENV_FILE=/etc/petcare/petcare.env

if [ "$(id -u)" -ne 0 ]; then echo "Ejecuta este script con sudo." >&2; exit 1; fi
if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Uso: sudo bash $0 <dominio> <correo>" >&2; exit 1
fi
if [ ! -f "$ENV_FILE" ]; then echo "Primero ejecuta deploy/setup.sh." >&2; exit 1; fi

echo "==> Comprobando que $DOMAIN apunte a esta instancia"
TOKEN=$(curl -sf -m 2 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
PUBLIC_IP=$(curl -sf -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
RESOLVED=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}')
if [ -z "$RESOLVED" ]; then
    echo "!! $DOMAIN no resuelve a ninguna IP. Revisa el registro en DuckDNS." >&2; exit 1
fi
if [ -n "$PUBLIC_IP" ] && [ "$RESOLVED" != "$PUBLIC_IP" ]; then
    echo "!! $DOMAIN apunta a $RESOLVED, pero la IP pública de esta instancia es $PUBLIC_IP." >&2
    echo "   Actualiza la IP en DuckDNS y vuelve a intentarlo en un par de minutos." >&2
    exit 1
fi

echo "==> Obteniendo el certificado"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q certbot
mkdir -p /var/www/certbot
certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" \
    --email "$EMAIL" --agree-tos --non-interactive --keep-until-expiring \
    --deploy-hook "systemctl reload nginx"

echo "==> Configurando Django para HTTPS"
set_env() {
    if grep -q "^$1=" "$ENV_FILE"; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
    else
        echo "$1=$2" >> "$ENV_FILE"
    fi
}
set_env PETCARE_HTTPS 1
set_env PETCARE_TRUST_PROXY 1
set_env PETCARE_EXTRA_HOSTS "$DOMAIN"
set_env PETCARE_CSRF_ORIGINS "https://$DOMAIN"
echo "$DOMAIN" > /etc/petcare/https-domain

echo "==> Configurando Nginx"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP_DIR/deploy/nginx-petcare-https.conf" > /etc/nginx/sites-available/petcare
nginx -t
systemctl reload nginx
systemctl restart petcare

sleep 2
if curl -sf -o /dev/null "https://$DOMAIN/ingresar/"; then
    echo "==> HTTPS activo: https://$DOMAIN/"
else
    echo "!! El sitio no respondió por HTTPS. Revisa: sudo journalctl -u petcare -n 50" >&2
fi
echo "El certificado se renueva automáticamente (certbot.timer)."
