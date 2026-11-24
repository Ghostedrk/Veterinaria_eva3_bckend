"""Respaldo programado de PetCare: snapshot manual de RDS cada 7 horas.

Se ejecuta desde Amazon EventBridge (regla programada "rate(7 hours)") y complementa los
respaldos automáticos diarios de RDS, que no permiten elegir una frecuencia de 7 horas.

Variables de entorno de la función:
    DB_INSTANCE     identificador de la instancia RDS (petcare-db)
    SNS_TOPIC_ARN   tema SNS para avisar el resultado (opcional)
    KEEP            cuántos snapshots de esta función conservar (por defecto 8 ≈ 2,3 días)

Rol de ejecución en AWS Academy: LabRole (permite rds:CreateDBSnapshot, rds:DescribeDBSnapshots,
rds:DeleteDBSnapshot y sns:Publish). Runtime: Python 3.12. Tiempo de espera: 30 segundos.
"""
import os
from datetime import datetime, timezone

import boto3

PREFIX = "petcare-7h-"
rds = boto3.client("rds")
sns = boto3.client("sns")


def notify(subject, message):
    topic = os.environ.get("SNS_TOPIC_ARN")
    if topic:
        sns.publish(TopicArn=topic, Subject=subject[:100], Message=message)


def lambda_handler(event, context):
    instance = os.environ["DB_INSTANCE"]
    keep = int(os.environ.get("KEEP", "8"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    snapshot_id = f"{PREFIX}{stamp}"
    try:
        rds.create_db_snapshot(
            DBInstanceIdentifier=instance,
            DBSnapshotIdentifier=snapshot_id,
            Tags=[{"Key": "creado-por", "Value": "lambda-respaldo-7h"}],
        )
        # Rotación: se eliminan los snapshots más antiguos creados por esta función.
        snapshots = rds.describe_db_snapshots(DBInstanceIdentifier=instance, SnapshotType="manual")["DBSnapshots"]
        own = sorted((s for s in snapshots if s["DBSnapshotIdentifier"].startswith(PREFIX)
                      and s.get("SnapshotCreateTime")), key=lambda s: s["SnapshotCreateTime"], reverse=True)
        deleted = []
        for old in own[keep:]:
            rds.delete_db_snapshot(DBSnapshotIdentifier=old["DBSnapshotIdentifier"])
            deleted.append(old["DBSnapshotIdentifier"])
    except Exception as exc:  # Se informa por SNS y se deja el error en CloudWatch Logs.
        notify("PetCare: falló el respaldo de RDS", f"No se pudo crear {snapshot_id} de {instance}: {exc}")
        raise
    message = (f"Snapshot {snapshot_id} de {instance} solicitado (cifrado, igual que la instancia). "
               f"Conservados: {min(len(own), keep)}. Eliminados: {', '.join(deleted) or 'ninguno'}.")
    print(message)  # Queda en CloudWatch Logs.
    notify("PetCare: respaldo de RDS creado", message)
    return {"snapshot": snapshot_id, "deleted": deleted}
