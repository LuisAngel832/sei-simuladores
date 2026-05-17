# files2/ — Simulador SEI + Panel de control

Emulador Python del Sistema de Enfriamiento Inteligente. Publica datos de
sensores (temperatura, presencia) en el broker EMQX 5.x conforme al
**Contrato MQTT v3.0** (`10_E7_Contrato_MQTT.docx`). Incluye un panel
desechable y wrappers CLI con flags para reproducir escenarios de los
4 Sprints sin pasar por el HMI.

## Arranque rapido

```bash
# 1. Broker EMQX corriendo (Docker o local). Configurar host:
$env:MQTT_HOST = "172.17.240.1"   # PowerShell
$env:MQTT_PORT = "1883"

# 2. Simulador continuo (5 cuartos, publica temperatura + presencia)
python main.py
# o con el wrapper PowerShell:
.\run_main_emqx.ps1

# 3. Panel interactivo (en otra terminal). Pide login al arrancar.
python -m panel.cli
```

## Wrappers CLI con flags

Cumplen al pie de la letra las tareas de Sprint que pedian comandos
ejecutables con flags (`python script.py --cuarto N --estado true`).
Conviven con el panel interactivo y reutilizan la misma logica de
`PanelPublisher` y `OverrideX`.

### `cli_presencia.py` — T-03-01 / T-07-01

Publica `sei/cuartos/{n}/presencia` con valor forzado.

```bash
python cli_presencia.py --cuarto 3 --estado true
python cli_presencia.py --cuarto 3 --estado false --duracion 60
```

### `cli_temperatura.py` — T-04-04

Override de `sei/cuartos/{n}/temperatura` en modo calentamiento, enfriamiento
o objetivo fijo.

```bash
python cli_temperatura.py --cuarto 2 --modo calentamiento --target 5
python cli_temperatura.py --cuarto 2 --modo enfriamiento --target -18
python cli_temperatura.py --cuarto 2 --modo objetivo --target 3.5 --duracion 120
```

### `cli_puerta.py` — T-06-01 (reformulado a v3.0)

Publica `sei/cuartos/{n}/puerta/cmd` con JWT real (login a `/api/login`)
o mock (fallback). Recordar: **el simulador no publica `/puerta` en v3.0**;
ese topico lo publica el Backend.

```bash
python cli_puerta.py --cuarto 3 --cmd forzar_apertura --usuario cruiz
python cli_puerta.py --cuarto 3 --cmd forzar_cierre --razon "limpieza"
python cli_puerta.py --cuarto 3 --cmd cancelar_cierre_auto --usuario jperez
```

## Variables de entorno

| Variable | Default | Uso |
|----------|---------|-----|
| `MQTT_HOST` | `192.168.1.100` | Host del broker EMQX |
| `MQTT_PORT` | `1883` | Puerto MQTT TCP |
| `BACKEND_HOST` | = `MQTT_HOST` | Host del backend Spring Boot |
| `BACKEND_PORT` | `8080` | Puerto REST del backend |
| `BACKEND_URL` | `http://{host}:{port}` | URL completa, override directo |
| `BACKEND_LOGIN_TIMEOUT_S` | `3.0` | Timeout del POST /api/login |
| `SEI_SIM_RUIDO` | `0.3` | Amplitud del ruido del sensor (T-01-02) |

## Cobertura por Sprint

| Sprint | Cubre | Como |
|--------|-------|------|
| Sprint 1 | HU-01, HU-02, HU-03 | `main.py` (5 cuartos, 30s/5s, ±0.3°C) + `cli_presencia.py` |
| Sprint 2 | HU-04, HU-05, HU-06, HU-08 | `cli_temperatura.py --modo calentamiento` + `cli_puerta.py --cmd forzar_apertura` + Escenario A/D |
| Sprint 3 | HU-07, HU-09, HU-10, HU-13 | Login real al arranque + `cli_puerta.py` con JWT + Escenarios B/C/E + opcion 90 (re-login) |
| Sprint 4 | HU-08, HU-11, HU-12 | `cli_puerta.py --cmd forzar_apertura` para HU-08; HU-11/12 son backend+HMI |

Pruebas de seguridad:
- **CP-AUTH-01** (operador OK en `cancelar_cierre_auto`): login como `jperez` y `cli_puerta.py --cmd cancelar_cierre_auto`.
- **CP-AUTH-02** (operador rechazado en silenciar): panel opcion 20 (Escenario G).
- **CP-LOGIN-01** (login OK): panel arranca, prompt de credenciales, ver `[Auth] [OK] Login real exitoso`.
- **CP-LOGIN-02** (login fallido): credenciales malas -> `[Auth] [WARN] Backend respondio 401`.

## Decision: Contrato v3.0 prevalece

Cuando un Sprint Planning contradice el Contrato MQTT v3.0 (caso T-06-01:
"simulador publica /puerta"), prevalece el contrato. La tarea original se
reformula al modelo v3.0 — el simulador no publica `/puerta` ni `/alarma`,
solo el Backend lo hace. El simulador y el panel publican `/cmd`. Ver
`panel/README.md` para la matriz completa Sprint -> mecanismo.

# sei-simuladores
