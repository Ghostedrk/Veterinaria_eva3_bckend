#!/usr/bin/env bash
# Detecta la IP y el DNS públicos de la instancia EC2 (IMDSv2) y los escribe en
# /run/petcare-hosts.env para ALLOWED_HOSTS. En AWS Academy la IP pública cambia
# cada vez que se reinicia el laboratorio, por eso se ejecuta en cada arranque.
set -u

OUT=/run/petcare-hosts.env
META=http://169.254.169.254/latest
HOSTS="localhost,127.0.0.1"

TOKEN=$(curl -sf -m 2 -X PUT "$META/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
meta() {
    curl -sf -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" "$META/meta-data/$1" || true
}
if [ -n "$TOKEN" ]; then
    for value in "$(meta public-ipv4)" "$(meta public-hostname)" "$(meta local-ipv4)"; do
        [ -n "$value" ] && HOSTS="$HOSTS,$value"
    done
fi

EXTRA=$(grep -E '^PETCARE_EXTRA_HOSTS=' /etc/petcare/petcare.env 2>/dev/null | cut -d= -f2- || true)
[ -n "$EXTRA" ] && HOSTS="$HOSTS,$EXTRA"

printf 'PETCARE_HOSTS=%s\n' "$HOSTS" > "$OUT"
chmod 644 "$OUT"
