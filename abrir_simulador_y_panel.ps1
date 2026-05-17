# Abre las ventanas necesarias para correr el sistema SEI completo:
#   1) Simulador Python  (files2/main.py)
#   2) Panel de control  (files2/panel/cli.py)
#   3) HMI server bridge (sei-hmi/server)
#   4) HMI client Vite   (sei-hmi/client)
#
# Uso:  .\abrir_simulador_y_panel.ps1
#       .\abrir_simulador_y_panel.ps1 -SoloHmi      # solo HMI
#       .\abrir_simulador_y_panel.ps1 -SoloSim      # solo simulador + panel
#
# Requisitos previos:
#   - EMQX corriendo en $MqttHost:1883
#   - npm install ya corrido en sei-hmi/server y sei-hmi/client
param(
    [string]$MqttHost = '192.168.100.52',
    [int]$MqttPort = 1883,
    [switch]$SoloHmi,
    [switch]$SoloSim
)

Set-Location $PSScriptRoot
$dirSim = $PSScriptRoot                                    # files2/
$dirHmi = Resolve-Path (Join-Path $PSScriptRoot '..\sei-hmi')

function Abrir-Ventana {
    param([string]$Titulo, [string]$WorkDir, [string]$Comando)
    Start-Process powershell -ArgumentList @(
        '-NoExit',
        '-Command',
        "Set-Location '$WorkDir'; `$host.UI.RawUI.WindowTitle='$Titulo'; $Comando"
    )
}

if (-not $SoloHmi) {
    Write-Host "[Launcher] Ventana 1: SEI Simulador (broker $MqttHost`:$MqttPort)"
    Abrir-Ventana -Titulo 'SEI Simulador' -WorkDir $dirSim `
        -Comando "`$env:MQTT_HOST='$MqttHost'; `$env:MQTT_PORT='$MqttPort'; python main.py"
    Start-Sleep -Seconds 2

    Write-Host "[Launcher] Ventana 2: SEI Panel"
    Abrir-Ventana -Titulo 'SEI Panel' -WorkDir $dirSim `
        -Comando "`$env:MQTT_HOST='$MqttHost'; `$env:MQTT_PORT='$MqttPort'; python -m panel.cli"
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
