# Arranca el simulador SEI cargando las variables desde .env.
# Para cambiar IPs: edita .env (no toques este script).
Set-Location $PSScriptRoot

$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] No se encontro .env en $envFile" -ForegroundColor Red
    Write-Host "  Copia .env.example a .env y ajusta MQTT_HOST / BACKEND_HOST."
    exit 1
}

# Parsea .env -> variables de entorno del proceso actual.
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $kv = $line -split '=', 2
        if ($kv.Length -eq 2) {
            Set-Item -Path "env:$($kv[0].Trim())" -Value $kv[1].Trim()
        }
    }
}

Write-Host "MQTT_HOST=$($env:MQTT_HOST):$($env:MQTT_PORT)"
Write-Host "BACKEND_HOST=$($env:BACKEND_HOST):$($env:BACKEND_PORT)"

python ".\main.py"
