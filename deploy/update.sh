#!/usr/bin/env bash
# Descarga los últimos cambios del repositorio y vuelve a aplicar la instalación.
# Uso: sudo bash /opt/petcare/deploy/update.sh
set -euo pipefail
cd /opt/petcare
sudo -u petcare git pull --ff-only
exec bash /opt/petcare/deploy/setup.sh
