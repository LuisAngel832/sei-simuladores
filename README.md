# SEI - Simuladores - Sistema de Enfriamiento Inteligente

Simuladores Python que emulan los sensores fisicos de los 5 cuartos frios del
SEI. Publican lecturas de temperatura y presencia al broker EMQX via MQTT
conforme al Contrato MQTT v3.0 (`10_E7_Contrato_MQTT.docx`) y sincronizan el
estado de puertas y refrigeracion con el backend Spring Boot.

Incluye un panel de control desechable y un grupo de wrappers CLI con flags
para reproducir escenarios de prueba contra el simulador y el backend sin
pasar por el HMI.

## Que simulan

- Temperatura de cada cuarto con variacion realista en el tiempo (+/-0.3 C
  por ciclo, deriva por puerta abierta y por accion del enfriador).
- Presencia humana mediante un modelo de "visitas" discretas: la mayor parte
  del tiempo el cuarto esta en reposo, esporadicamente se inicia una visita
  de carga/descarga que dura unos pocos ciclos y luego termina.
- Apertura y cierre de puertas condicionado a presencia detectada, con la
  logica final de cierre/cancelacion delegada al backend.
- Sincronizacion con el backend via topicos de comando MQTT (puerta/cmd,
  refrigeracion/cmd, alarma/cmd) con autenticacion JWT real o mock.

## Requisitos previos

- Python >= 3.10
- pip
- Broker EMQX 5.x accesible en la red del laboratorio (puerto 1883)
- Opcional: backend Spring Boot del SEI corriendo en el puerto 8080 para
  pruebas end-to-end con login real y validacion de JWT.

## Instalacion

```bash
git clone https://github.com/LuisAngel832/sei-simuladores.git
cd sei-simuladores
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuracion

```bash
cp .env.example .env
# Editar .env y ajustar MQTT_HOST a la IP del Servidor SEI en la LAN.
```

Las variables de entorno se cargan via `os.getenv` directamente desde el
ambiente del proceso. El simulador no usa `python-dotenv`; cargar el `.env`
es responsabilidad del shell (`source .env` en bash, o exportar las
variables a mano antes de arrancar). En PowerShell se setean con
`$env:MQTT_HOST = "..."`.

Variables principales (ver `.env.example` para la lista completa):

| Variable | Default | Uso |
|----------|---------|-----|
| `MQTT_HOST` | `192.168.1.100` | Host del broker EMQX |
| `MQTT_PORT` | `1883` | Puerto MQTT TCP |
| `BACKEND_HOST` | = `MQTT_HOST` | Host del backend Spring Boot (solo panel) |
| `BACKEND_PORT` | `8080` | Puerto REST del backend |
| `BACKEND_URL` | `http://{host}:{port}` | URL completa, override directo |
| `BACKEND_LOGIN_TIMEOUT_S` | `3.0` | Timeout del POST /api/login |
| `SEI_SIM_RUIDO` | `0.3` | Amplitud del ruido del sensor (T-01-02) |
| `SEI_SIM_PROB_VISITA` | `0.04` | Prob. por ciclo de iniciar una visita |
| `SEI_SIM_VISITA_MIN_CICLOS` | `2` | Duracion minima de la visita |
| `SEI_SIM_VISITA_MAX_CICLOS` | `5` | Duracion maxima de la visita |

## Ejecutar

### Windows (PowerShell)

```powershell
# Simulador principal (5 cuartos)
.\run_main_emqx.ps1

# Panel de control interactivo (en otra terminal)
python -m panel.cli

# Lanzar simulador, panel y el resto del sistema en ventanas separadas
.\abrir_simulador_y_panel.ps1 -MqttHost 192.168.1.100
```

### Linux / macOS (bash)

```bash
# Simulador principal
./run_main_emqx.sh

# o invocando python directamente con override de host
MQTT_HOST=192.168.1.100 python main.py

# Panel de control interactivo
python -m panel.cli
```

### Wrappers CLI con flags

```bash
# Forzar presencia (T-03-01 / T-07-01)
python cli_presencia.py --cuarto 3 --estado true
python cli_presencia.py --cuarto 3 --estado false --duracion 60

# Forzar temperatura (T-04-04)
python cli_temperatura.py --cuarto 2 --modo calentamiento --target 5
python cli_temperatura.py --cuarto 2 --modo enfriamiento --target -18
python cli_temperatura.py --cuarto 2 --modo objetivo --target 3.5 --duracion 120

# Comandos de puerta firmados con JWT (T-06-01 reformulado)
python cli_puerta.py --cuarto 3 --cmd forzar_apertura --usuario cruiz
python cli_puerta.py --cuarto 3 --cmd forzar_cierre --razon "limpieza"
python cli_puerta.py --cuarto 3 --cmd cancelar_cierre_auto --usuario jperez
```

## Topicos MQTT publicados

| Topico | QoS | Retain | Origen | Modulo |
|--------|-----|--------|--------|--------|
| `sei/cuartos/{n}/temperatura` | 0 | true | Simulador / panel override | `mqtt_broker.py`, `panel/overrider.py` |
| `sei/cuartos/{n}/presencia` | 1 | true | Simulador / panel override | `mqtt_broker.py`, `panel/overrider.py` |
| `sei/cuartos/{n}/puerta/cmd` | 1 | false | Panel / `cli_puerta.py` | `panel/publisher.py` |
| `sei/cuartos/{n}/refrigeracion/cmd` | 1 | false | Panel | `panel/publisher.py` |
| `sei/cuartos/{n}/alarma/cmd` | 1 | false | Panel (CP-AUTH-02 / HU-09) | `panel/publisher.py` |
| `sei/panel/override/temperatura/{n}` | 1 | true | Panel (anuncio de override) | `panel/overrider.py` |

n = 1..5.

## Topicos MQTT suscritos

| Topico | QoS | Quien publica | Uso en el simulador |
|--------|-----|---------------|---------------------|
| `sei/cuartos/+/alarma` | 1 | Backend | Sincroniza estado de alarma local |
| `sei/cuartos/+/puerta` | 1 | Backend | Sincroniza estado y notifica al actuador Puerta |
| `sei/sistema/estado` | 1 | Backend | Hidrata el estado global al arrancar |
| `sei/cuartos/+/puerta/cmd` | 1 | HMI / panel | Aplica efecto local en el actuador Puerta |
| `sei/cuartos/+/refrigeracion/cmd` | 1 | HMI / panel | Aplica efecto local en el Enfriador |
| `sei/cuartos/+/temperatura` | 0 | Panel / otros | Refresca el cache compartido (overrides) |
| `sei/panel/override/temperatura/+` | 1 | Panel | Detiene la publicacion del simulador cuando hay override |
| `sei/sistema/seguridad` | 1 | Backend | Listener del panel (`SecurityListener`) para imprimir rechazos |

## Estructura del proyecto

```
sei-simuladores/
├── .env.example                  Plantilla de variables de entorno
├── .gitignore
├── README.md                     Este archivo
├── requirements.txt              Dependencias Python
├── run_main_emqx.ps1             Arranque del simulador en PowerShell
├── run_main_emqx.sh              Arranque del simulador en bash
├── abrir_simulador_y_panel.ps1   Lanzador de ventanas (simulador, panel, HMI)
├── main.py                       Orquestador del simulador (5 cuartos)
├── mqtt_broker.py                Publisher y Subscriber MQTT del simulador
├── sensores.py                   SensorTemperatura y SensorMovimiento
├── actuadores.py                 Puerta, CortinaDeAire, Enfriador, Alarma
├── cli_presencia.py              Wrapper CLI para forzar presencia
├── cli_temperatura.py            Wrapper CLI para forzar temperatura
├── cli_puerta.py                 Wrapper CLI para puerta/cmd (con JWT)
└── panel/                        Panel de control desechable
    ├── README.md                 Documentacion interna del panel
    ├── __init__.py
    ├── auth.py                   Login real /api/login + fallback mock
    ├── cli.py                    Menu interactivo del panel
    ├── publisher.py              Cliente MQTT del panel (topics /cmd)
    ├── overrider.py              Hilos OverrideTemperatura / OverridePresencia
    ├── escenarios.py             Escenarios pre-armados A-G (CP-SYS-01)
    ├── operaciones.py            Escenarios de operacion D1-D15
    └── security_listener.py      Listener de sei/sistema/seguridad
```

## Dependencias del sistema completo

Para ejercitar el simulador end-to-end con autenticacion real y autoridad
de alarmas hace falta el ecosistema completo del SEI:

- **EMQX 5.x** corriendo en `MQTT_HOST:1883`. Dashboard de monitoreo en
  `http://MQTT_HOST:18083`.
- **Backend Spring Boot** (`BackEnfriadores`) en `BACKEND_HOST:8080` -
  publica `sei/cuartos/{n}/alarma`, `sei/cuartos/{n}/puerta`,
  `sei/sistema/estado` y `sei/sistema/seguridad`, valida JWTs y persiste
  audit trail.
- **HMI** (`sei-hmi`) opcional - visualizacion en navegador. El simulador
  funciona sin HMI; el panel cubre todos los escenarios de prueba.

Sin backend, el simulador y el panel siguen funcionando: el panel hace
fallback a una sesion mock con JWT de firma invalida (util para validar
formato de mensajes sin autenticacion real) y el simulador aplica los
efectos locales de los comandos.

## Comportamiento de ciclos simulados

### Frecuencia de muestreo

- Estado normal: ciclo cada **30 s** (publica temperatura y presencia).
- Cualquier cuarto con alarma activa: ciclo cada **5 s**.

El simulador detecta automaticamente el cambio de frecuencia leyendo el
estado de alarma local de cada cuarto (`Alarma.estado != "normal"`).

### Modelo de presencia (visitas)

`SensorMovimiento` mantiene el cuarto en reposo (presencia = false) la mayor
parte del tiempo. En cada ciclo en reposo existe una probabilidad
`SEI_SIM_PROB_VISITA` (default 4%) de iniciar una visita; la visita dura
entre `SEI_SIM_VISITA_MIN_CICLOS` y `SEI_SIM_VISITA_MAX_CICLOS` ciclos
(default 2 a 5, equivalentes a 60-150 s con ciclos de 30 s) y termina
automaticamente.

### Deriva termica

En cada ciclo se calcula una deriva total que se aplica al sensor:

```
deriva = +0.02 C                       (calentamiento natural baseline)
       + 0.06 C  si la cortina esta activa
       - 0.20 * (potencia_pct / 100)  si el enfriador esta encendido
```

Mas un ruido aleatorio uniforme de `+/- SEI_SIM_RUIDO` (default +/-0.3 C).

### Umbrales de alarma

`SensorTemperatura.leer()` y `Alarma.evaluar()` clasifican la temperatura:

| Rango | Estado |
|-------|--------|
| `< 3.0 C` | normal |
| `3.0 - 4.0 C` | preventiva |
| `> 4.0 C` | critica |

El simulador solo registra el estado local; la autoridad de alarmas la
ejerce el backend, que publica el resultado oficial en
`sei/cuartos/{n}/alarma`.

### Limpieza de mensajes retenidos

Al cerrar el simulador con Ctrl+C, el `Publisher` borra los mensajes
retenidos de `sei/cuartos/{n}/temperatura` y `sei/cuartos/{n}/presencia`
para que el HMI no muestre valores viejos en el siguiente arranque.

## Decision: Contrato v3.0 prevalece

Cuando un Sprint Planning contradice el Contrato MQTT v3.0 (caso T-06-01:
"simulador publica /puerta"), prevalece el contrato. La tarea original se
reformula al modelo v3.0: el simulador no publica `/puerta` ni `/alarma`,
solo el Backend lo hace. El simulador y el panel publican `/cmd`.

Ver `panel/README.md` para la matriz completa Sprint -> mecanismo y el
mapa de escenarios pre-armados (A-G, D1-D15).
