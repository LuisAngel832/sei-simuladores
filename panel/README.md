# Panel de control desechable

Herramienta de pruebas para disparar escenarios contra el simulador y el backend
sin pasar por el HMI. **No es parte del sistema productivo** — se usa solo para
ensayos manuales y demos.

## Que hace

Publica en el broker EMQX exclusivamente en topics definidos por el
`Contrato MQTT v3.0` (`10_E7_Contrato_MQTT.docx`). No agrega topics nuevos
ni modifica el simulador en `files2/`.

## Como arrancar

Desde `files2/` (un nivel arriba de `panel/`):

```bash
# Asumiendo que el broker EMQX esta corriendo en el host configurado
python -m panel.cli
```

Si el broker no esta en `192.168.1.100:1883`, exporta:

```bash
# bash
export MQTT_HOST=192.168.137.9
export MQTT_PORT=1883

# powershell
$env:MQTT_HOST = "192.168.137.9"
$env:MQTT_PORT = "1883"
```

## Para desecharlo

Borrar la carpeta entera. El simulador queda intacto.

```bash
rm -rf files2/panel/
```

## Estado del desarrollo

- [x] Iteracion 0: setup base, conexion al broker, menu vacio.
- [x] Iteracion 1: forzar calentamiento / enfriamiento / objetivo de un cuarto (HU-04, HU-05).
- [x] Iteracion 2: comandos de puerta (forzar_apertura / forzar_cierre / cancelar_cierre_auto). Cubre HU-06, HU-08.
- [x] Iteracion 3: forzar presencia ON/OFF (HU-03, HU-07).
- [x] Iteracion 4: forzar encendido / cancelar forzado de refrigeracion (HU-10).
- [x] Iteracion 5: escenarios pre-armados A-F (CP-SYS-01).
- [x] Iteracion 6: login real a `/api/login` con fallback mock + selector
      de usuario al arranque + listener de `sei/sistema/seguridad` +
      escenario G (CP-AUTH-02). Cubre HU-13.

## Escenarios pre-armados (Iter 5 + 6)

| # | Escenario | Cubre |
|---|-----------|-------|
| A | Escalada de alarma | HU-04, HU-05 |
| B | Cierre automatico sin presencia | HU-07 |
| C | Cancelacion de cierre por presencia | HU-07 |
| D | Apertura, cortina y potencia | HU-06, HU-08 |
| E | Forzar refrigeracion | HU-10 |
| F | CP-SYS-01 completo (A→D→B→C→E con pausas) | Sprint Review |
| G | Operador intenta silenciar (rechazado) | HU-13, CP-AUTH-02 |

Los escenarios B, C, D, E, G requieren backend Java arriba para validacion
end-to-end. Sin backend solo verifican que el panel emite los comandos
correctos y el simulador aplica los efectos locales (CortinaDeAire,
Enfriador, Puerta).

## Autenticacion (Iter 6)

Al arrancar `python -m panel.cli` se pide usuario y password. El panel hace
`POST /api/login` (ver `panel/auth.py`) con timeout de 3 s; si el backend
responde, los comandos /cmd llevan el JWT firmado real. Si el backend no
responde, se usa una **sesion mock** con JWT de firma invalida — utiles
para pruebas locales sin backend, pero el backend Java los rechazara cuando
este arriba (eso queda registrado en `sei/sistema/seguridad`).

Usuarios sugeridos (Sprint 3 / 4):
| Usuario | Rol | Password |
|---------|-----|----------|
| jperez  | operador   | 1234 (T-13-01) |
| alopez  | supervisor | 5678 (T-13-01) |
| cruiz   | supervisor / auditor | indefinido en Sprint 4 |

Override por entorno: `BACKEND_HOST`, `BACKEND_PORT`, `BACKEND_URL`,
`BACKEND_LOGIN_TIMEOUT_S`. Por defecto se reutiliza `MQTT_HOST` con
puerto 8080.

## Mapa Sprint -> mecanismo en files2/

| Tarea Sprint | Forma original | Mecanismo en files2 |
|--------------|----------------|---------------------|
| T-01-02 / T-01-03 | Simulador 5 cuartos cada 30 s ±0.3°C | `main.py` + `sensores.py` (RUIDO_AMPLITUD=0.3 por env `SEI_SIM_RUIDO`) |
| T-03-01 / T-07-01 | `python presencia.py --cuarto N --estado true\|false` | `cli_presencia.py --cuarto N --estado true\|false [--duracion S]` o panel opciones 9/10 |
| T-04-04 | `python sim --modo calentamiento` | `cli_temperatura.py --cuarto N --modo calentamiento --target 5` o panel opcion 1 |
| T-06-01 | Simulador publica `/puerta` | **Reemplazado por contrato v3.0**: `cli_puerta.py --cuarto N --cmd forzar_apertura` publica `/puerta/cmd`; el Backend publica `/puerta` |
| T-08-04 / T-08-05 | Abrir puerta cuarto 2 desde simulador | `cli_puerta.py --cuarto 2 --cmd forzar_apertura` o panel opcion 6 / Escenario D |
| T-10-06 / T-12-04 | Probar como jperez vs alopez | Re-login con opcion 90 del panel + Escenario G (CP-AUTH-02) |
| T-13-10 | CP-LOGIN-01/02 + CP-AUTH-01/02 | Panel hace login real al arranque; SecurityListener imprime rechazos |
