#!/usr/bin/env bash
# Análisis dinámico (DAST) con OWASP ZAP Baseline sobre la aplicación propia desplegada.
# ZAP Baseline hace una exploración (spider) y un análisis PASIVO: no ataca ni modifica datos.
#
# Uso (en la EC2 frontend, que es un entorno autorizado del propio proyecto):
#   sudo bash /opt/petcare-src/deploy/zap-scan.sh http://<IP-frontend>/ https://petcare-sfvet.duckdns.org/
# Los informes quedan en /home/ubuntu/zap/ (HTML, JSON y Markdown).
set -euo pipefail

if [ "$(id -u)" -ne 0 ] || [ "$#" -lt 1 ]; then
    echo "Uso: sudo bash $0 <url1> [url2 ...]" >&2
    exit 1
fi
OUT=/home/ubuntu/zap
install -d -o ubuntu -g ubuntu "$OUT"
chmod 777 "$OUT"  # El contenedor de ZAP escribe como usuario sin privilegios.

if ! command -v docker >/dev/null; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io
    systemctl enable --now docker
fi
docker pull -q ghcr.io/zaproxy/zaproxy:stable

n=0
for target in "$@"; do
    n=$((n + 1))
    name="zap-$n-$(echo "$target" | sed -E 's#https?://##; s#[^A-Za-z0-9]+#-#g; s#-$##')"
    echo "==> ZAP Baseline sobre $target"
    # Código de salida: 0 sin alertas, 1 FAIL, 2 WARN. Se registra pero no detiene el script.
    docker run --rm -v "$OUT":/zap/wrk:rw ghcr.io/zaproxy/zaproxy:stable \
        zap-baseline.py -t "$target" -m 2 -r "$name.html" -J "$name.json" -w "$name.md" -I || true
done
chown -R ubuntu:ubuntu "$OUT"
echo
echo "Informes en $OUT:"
ls -1 "$OUT"
echo "Descárgalos a tu PC con: scp -i labsuser.pem ubuntu@<IP>:~/zap/*.html ."
