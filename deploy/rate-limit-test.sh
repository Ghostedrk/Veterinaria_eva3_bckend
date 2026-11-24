#!/usr/bin/env bash
# Prueba del rate limit de Amazon API Gateway desde Linux/macOS o una EC2.
# Uso: bash deploy/rate-limit-test.sh https://<id>.execute-api.us-east-1.amazonaws.com/api/salud/ [total]
set -u
URL=${1:?Uso: bash $0 <url> [total]}
TOTAL=${2:-30}
echo "Enviando $TOTAL solicitudes simultáneas a $URL"
seq "$TOTAL" | xargs -P "$TOTAL" -I{} curl -s -o /dev/null -w "%{http_code}\n" "$URL" | sort | uniq -c \
    | awk '{ printf "  HTTP %s: %s solicitudes%s\n", $2, $1, ($2 == 429 ? "  <- limitadas por API Gateway" : "") }'
