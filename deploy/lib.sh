#!/usr/bin/env bash
# Funciones compartidas por los scripts de despliegue.
ENV_FILE=/etc/petcare/petcare.env

# set_env CLAVE VALOR: crea o reemplaza una variable en el archivo de entorno.
set_env() {
    if grep -q "^$1=" "$ENV_FILE"; then
        local escaped
        escaped=$(printf '%s' "$2" | sed 's/[&|\\]/\\&/g')
        sed -i "s|^$1=.*|$1=$escaped|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
    fi
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "Ejecuta este script con sudo." >&2
        exit 1
    fi
}
