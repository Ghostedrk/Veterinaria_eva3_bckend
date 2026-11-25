#!/usr/bin/env bash
# Instala el frontend de PetCare en su propia EC2 (Nginx sirviendo archivos estáticos).
#
# Uso, en la EC2 frontend:
#   sudo git clone https://github.com/Ghostedrk/Veterinaria_eva3_bckend.git /opt/petcare-src
#   sudo bash /opt/petcare-src/deploy/frontend-setup.sh https://<id>.execute-api.us-east-1.amazonaws.com
set -euo pipefail

API_BASE=${1:-}
SRC=$(cd "$(dirname "$0")/.." && pwd)
WEB=/var/www/petcare-frontend

if [[ "$(id -u)" -ne 0 ]] || [[ -z "$API_BASE" ]]; then
    echo "Uso: sudo bash $0 https://<id>.execute-api.us-east-1.amazonaws.com" >&2
    exit 1
fi
API_BASE=${API_BASE%/}

apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx git curl

install -d -m 755 "$WEB" "$WEB/assets"
install -m 644 "$SRC"/frontend/index.html "$SRC"/frontend/app.js "$SRC"/frontend/styles.css "$WEB/"
install -m 644 "$SRC"/frontend/assets/* "$WEB/assets/"
printf 'window.PETCARE_CONFIG = { apiBase: "%s" };\n' "$API_BASE" > "$WEB/config.js"
chmod 644 "$WEB/config.js"

cat > /etc/nginx/sites-available/petcare-frontend <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    server_tokens off;
    root $WEB;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript image/svg+xml;

    # Cabeceras de seguridad: el navegador solo ejecuta código de este origen y solo
    # se conecta a la API de API Gateway.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' $API_BASE; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    location = /config.js { add_header Cache-Control "no-cache"; add_header Content-Security-Policy "default-src 'self'" always; }
    location / { try_files \$uri \$uri/ /index.html; }
}
EOF
ln -sf /etc/nginx/sites-available/petcare-frontend /etc/nginx/sites-enabled/petcare-frontend
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

TOKEN=$(curl -sf -m 2 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
IP=$(curl -sf -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
echo
echo "Frontend listo en http://${IP:-<IP-publica>}/  ·  API: $API_BASE"
echo "Prueba de la API vía API Gateway: $(curl -s -o /dev/null -w '%{http_code}' "$API_BASE/api/salud/") (esperado 200)"
