Set-Location $PSScriptRoot

# Host de EMQX en Docker detectado localmente
$env:MQTT_HOST = "172.17.240.1"
$env:MQTT_PORT = "1883"
$env:MQTT_DASHBOARD_URL = "http://$($env:MQTT_HOST):18083"

Write-Host "MQTT_HOST=$($env:MQTT_HOST)"
Write-Host "MQTT_PORT=$($env:MQTT_PORT)"
Write-Host "MQTT_DASHBOARD_URL=$($env:MQTT_DASHBOARD_URL)"

# Usa python directamente (evita bloqueos de seguridad)
python ".\\main.py"
