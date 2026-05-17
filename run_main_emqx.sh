#!/usr/bin/env bash
# Arranque del simulador SEI contra el broker EMQX en Linux/macOS.
# Equivalente del run_main_emqx.ps1 para entornos POSIX.
#
# Uso:
#   ./run_main_emqx.sh                 # usa los defaults definidos abajo
#   MQTT_HOST=10.0.0.5 ./run_main_emqx.sh
#
# Salida con codigo distinto de 0 si falla cualquier paso.

set -euo pipefail

cd "$(dirname "$0")"

# Host de EMQX en el laboratorio. Se puede sobreescribir exportando MQTT_HOST.
export MQTT_HOST="${MQTT_HOST:-172.17.240.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_DASHBOARD_URL="${MQTT_DASHBOARD_URL:-http://${MQTT_HOST}:18083}"

echo "MQTT_HOST=${MQTT_HOST}"
echo "MQTT_PORT=${MQTT_PORT}"
echo "MQTT_DASHBOARD_URL=${MQTT_DASHBOARD_URL}"

# Usar python3 si esta disponible, sino python.
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
fi

exec "${PYTHON_BIN}" ./main.py
