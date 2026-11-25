#!/usr/bin/env bash
# Mueve estáticos y archivos de la aplicación a un bucket S3 privado.
#
# Uso: sudo bash /opt/petcare/deploy/enable-s3.sh <nombre-del-bucket>
#
# Requisitos: la EC2 tiene el rol LabInstanceProfile (credenciales temporales de IAM,
# sin claves en el código) y el bucket tiene Block Public Access y cifrado SSE-S3.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
require_root

BUCKET=${1:-}
if [[ -z "$BUCKET" ]]; then
    echo "Uso: sudo bash $0 <nombre-del-bucket>" >&2
    exit 1
fi

set_env PETCARE_S3_BUCKET "$BUCKET"
set_env PETCARE_S3_REGION us-east-1

echo "==> Verificando acceso al bucket con el rol de la instancia"
petcare-manage shell -c "
import boto3
s3 = boto3.client('s3', region_name='us-east-1')
identity = boto3.client('sts').get_caller_identity()['Arn']
print('Identidad IAM:', identity)
enc = s3.get_bucket_encryption(Bucket='$BUCKET')['ServerSideEncryptionConfiguration']['Rules'][0]
print('Cifrado:', enc['ApplyServerSideEncryptionByDefault']['SSEAlgorithm'])
pab = s3.get_public_access_block(Bucket='$BUCKET')['PublicAccessBlockConfiguration']
print('Block Public Access:', all(pab.values()))
"

echo "==> Subiendo estáticos versionados a s3://$BUCKET/static/"
petcare-manage collectstatic --noinput -v 0

if [[ -d /var/lib/petcare/media ]] && [[ -n "$(find /var/lib/petcare/media -type f 2>/dev/null | head -1)" ]]; then
    echo "==> Copiando adjuntos existentes a s3://$BUCKET/media/"
    petcare-manage migrar_media_s3 /var/lib/petcare/media
fi

systemctl restart petcare
rm -rf /var/cache/nginx/petcare-static/* && systemctl reload nginx
sleep 2
CSS=$(curl -s -H 'Host: localhost' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/ingresar/ | grep -o '/static/clinic/panel[^"]*css' | head -1 || true)
echo "Estático servido desde S3: $CSS"
echo "Listo: el bucket sigue privado; la app entrega los estáticos y firma URL temporales para descargas."
