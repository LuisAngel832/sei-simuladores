#!/usr/bin/env bash
# Arranca el simulador SEI cargando las variables desde .env.
# Para cambiar IPs: edita .env (no toques este script).

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "[ERROR] No se encontro .env en $(pwd)"
    echo "  Copia .env.example a .env y ajusta MQTT_HOST / BACKEND_HOST."
    exit 1
fi

# Carga .env exportando cada KEY=VALUE al entorno del proceso.
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "MQTT_HOST=${MQTT_HOST}:${MQTT_PORT}"
echo "BACKEND_HOST=${BACKEND_HOST}:${BACKEND_PORT}"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
fi

exec "${PYTHON_BIN}" ./main.py
