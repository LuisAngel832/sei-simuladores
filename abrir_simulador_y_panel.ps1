# Abre las ventanas necesarias para correr el sistema SEI completo:
#   1) Simulador Python  (main.py)
#   2) Panel CLI         (panel.cli)
#   3) HMI server bridge (sei-hmi/server)
#   4) HMI client Vite   (sei-hmi/client)
#
# Las IPs de EMQX y backend se leen de .env (cambialas alli, no aqui).
#
# Uso:  .\abrir_simulador_y_panel.ps1
#       .\abrir_simulador_y_panel.ps1 -SoloHmi      # solo HMI
#       .\abrir_simulador_y_panel.ps1 -SoloSim      # solo simulador + panel
#
# Requisitos previos:
#   - .env presente en este directorio (copiar de .env.example)
#   - EMQX corriendo en MQTT_HOST:MQTT_PORT
#   - npm install ya corrido en sei-hmi/server y sei-hmi/client
param(
    [switch]$SoloHmi,
    [switch]$SoloSim
)

Set-Location $PSScriptRoot
$dirSim = $PSScriptRoot
$dirHmi = Resolve-Path (Join-Path $PSScriptRoot '..\sei-hmi')

$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] No se encontro .env en $envFile" -ForegroundColor Red
    Write-Host "  Copia .env.example a .env y ajusta MQTT_HOST / BACKEND_HOST."
    exit 1
}

# Parsea .env a un hash para reinyectar las variables en cada ventana hija.
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
        $kv = $line -split '=', 2
        if ($kv.Length -eq 2) {
            $envVars[$kv[0].Trim()] = $kv[1].Trim()
        }
    }
}

# Construye un prefijo "$env:KEY='VAL'; ..." para usar en cada ventana hija.
$exports = ($envVars.GetEnumerator() | ForEach-Object {
    "`$env:$($_.Key)='$($_.Value)'"
}) -join '; '

function Abrir-Ventana {
    param([string]$Titulo, [string]$WorkDir, [string]$Comando)
    Start-Process powershell -ArgumentList @(
        '-NoExit',
        '-Command',
        "Set-Location '$WorkDir'; `$host.UI.RawUI.WindowTitle='$Titulo'; $Comando"
    )
}

if (-not $SoloHmi) {
    Write-Host "[Launcher] Ventana 1: SEI Simulador (broker $($envVars.MQTT_HOST):$($envVars.MQTT_PORT))"
    Abrir-Ventana -Titulo 'SEI Simulador' -WorkDir $dirSim `
        -Comando "$exports; python main.py"
    Start-Sleep -Seconds 2

    Write-Host "[Launcher] Ventana 2: SEI Panel (backend $($envVars.BACKEND_HOST):$($envVars.BACKEND_PORT))"
    Abrir-Ventana -Titulo 'SEI Panel' -WorkDir $dirSim `
        -Comando "$exports; python -m panel.cli"
}

if (-not $SoloSim) {
    Start-Sleep -Seconds 1
    Write-Host "[Launcher] Ventana 3: HMI server bridge (puerto 3000)"
    Abrir-Ventana -Titulo 'SEI HMI server' -WorkDir $dirHmi.Path `
        -Comando "Set-Location server; node index.js"
    Start-Sleep -Seconds 2

    Write-Host "[Launcher] Ventana 4: HMI client Vite (puerto 5173)"
    Abrir-Ventana -Titulo 'SEI HMI client' -WorkDir $dirHmi.Path `
        -Comando "Set-Location client; npm run dev"
}

Write-Host ""
Write-Host "Listo. Abre http://localhost:5173 en el navegador para el HMI."
Write-Host "Diagnostico bridge: http://localhost:3000/diag/mqtt"
