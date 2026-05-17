"""
SEI - Sistema de Enfriamiento Inteligente
Orquestador principal del emulador — Contrato v2.0

Cambios respecto a v1.0:
  - Broker: EMQX 5.x en 192.168.1.100:1883
  - Puerta ya no recibe referencia al publisher (no publica).
  - Enfriador ya no recibe referencia al publisher (no publica).
  - El Subscriber recibe el publisher como parámetro para sincronizar
    publisher.cuartos[] cuando llegan mensajes del backend.
  - El heartbeat sei/sistema/estado lo publica el Backend; el simulador
    no lo genera. Se elimina CICLOS_POR_HEARTBEAT.
  - Alarma.evaluar() devuelve bool para ajustar frecuencia de muestreo:
    True = estado cambió (podría activarse modo rápido en el futuro).

Flujo por ciclo:
  1. sensor_temp.leer()           -> publisher.publicar_temperatura()
  2. sensor_mov.leer()            -> publisher.publicar_presencia()
  3. alarma.evaluar(temp)         -> actualiza estado local (sin publicar)
  4. puerta.evaluar_condiciones() -> actualiza estado local (sin publicar)
  5. cortina.sincronizar_con_puerta()
  6. enfriador.evaluar_temperatura()
  7. deriva = 0.02 + cortina + enfriador -> sensor_temp.set_deriva()
  8. publisher.cuartos[n]["puerta"] sincronizado desde estado local

Uso:
  pip install paho-mqtt
  # Asegurarse de que EMQX corra en 192.168.1.100:1883
  python main.py
"""

import time
import signal
import sys
from sensores import SensorTemperatura, SensorMovimiento
from actuadores import Puerta, CortinaDeAire, Enfriador, Alarma
from mqtt_broker import Publisher, Subscriber, BROKER_HOST

NUM_CUARTOS = 5
INTERVALO_NORMAL_SEGUNDOS = 30
INTERVALO_ALARMA_SEGUNDOS = 5


def construir_sistema():
    publisher = Publisher()

    cuartos = {}
    for n in range(1, NUM_CUARTOS + 1):
        cuartos[n] = {
            "sensor_temp": SensorTemperatura(n),
            "sensor_mov": SensorMovimiento(n),
            # v2.0: Puerta y Enfriador ya no reciben publisher
            "puerta": Puerta(n),
            "cortina": CortinaDeAire(n),
            "enfriador": Enfriador(n),
            "alarma": Alarma(n),
            "presencia_inicial_enviada": False,
        }

    # El Subscriber necesita el publisher (para sincronizar cuartos[])
    # y los actuadores (para despachar comandos y estado del backend)
    actuadores_por_cuarto = {
        n: {
            "puerta": cuartos[n]["puerta"],
            "enfriador": cuartos[n]["enfriador"],
            "alarma": cuartos[n]["alarma"],
        }
        for n in range(1, NUM_CUARTOS + 1)
    }
    subscriber = Subscriber(publisher, actuadores_por_cuarto)
    return publisher, subscriber, cuartos


def ciclo_cuarto(n, componentes, publisher):
    sensor_temp = componentes["sensor_temp"]
    sensor_mov = componentes["sensor_mov"]
    puerta = componentes["puerta"]
    cortina = componentes["cortina"]
    enfriador = componentes["enfriador"]
    alarma = componentes["alarma"]

    # 1. Leer y publicar sensores (los únicos tópicos que publica el simulador)
    payload_temp = sensor_temp.leer()
    if publisher.panel_overrides_temp.get(n, False):
        # El panel está forzando la temperatura del cuarto; no publicamos para
        # no pisar su valor. Resincronizamos el sensor interno con la
        # temperatura conocida del broker (actualizada por el Subscriber)
        # para no saltar bruscamente cuando el override se detenga.
        sensor_temp._temperatura = publisher.cuartos[n]["temperatura"]
        payload_temp["temperatura"] = sensor_temp._temperatura
    else:
        publisher.publicar_temperatura(payload_temp)

    payload_pres = sensor_mov.leer()
    presencia_prev = publisher.cuartos[n]["presencia"]
    presencia_actual = payload_pres["presencia"]
    if (not componentes["presencia_inicial_enviada"]) or (
        presencia_actual != presencia_prev
    ):
        publisher.publicar_presencia(payload_pres)
        componentes["presencia_inicial_enviada"] = True

    temp_actual = payload_temp["temperatura"]
    hay_presencia = presencia_actual

    # 2. Lógica de actuadores (sin publicar — el backend decide y publica)
    alarma.evaluar(temp_actual)
    puerta.evaluar_condiciones(hay_presencia, temp_actual)
    cortina.sincronizar_con_puerta(puerta.estado)
    enfriador.evaluar_temperatura(temp_actual)

    # 3. Derivas térmicas: calentamiento natural + cortina - enfriador
    deriva = 0.02 + cortina.influencia_termica() + enfriador.influencia_termica()
    sensor_temp.set_deriva(deriva)

    # 4. Sincronizar estado de puerta en publisher.cuartos para el heartbeat
    publisher.cuartos[n]["puerta"] = puerta.estado
    publisher.cuartos[n]["alarma"] = alarma.estado


def main():
    print("=" * 60)
    print("   SEI - Sistema de Enfriamiento Inteligente")
    print(f"   Emulador MQTT v2.0 | Broker EMQX: {BROKER_HOST}")
    print("=" * 60)

    publisher, subscriber, cuartos = construir_sistema()

    try:
        publisher.conectar()
        time.sleep(1)
        subscriber.conectar()
        time.sleep(1)
    except Exception as e:
        print(f"\n[Main] No se pudo conectar al broker EMQX: {e}")
        print(f"[Main] Verifica que EMQX este corriendo en {BROKER_HOST}:1883")
        sys.exit(1)

    ciclo = 0

    def salir(sig, frame):
        print("\n[Main] Cerrando emulador...")
        # Borra los mensajes retained del simulador en el broker para que el
        # HMI no reciba valores viejos al reconectar despues de un apagado.
        publisher.limpiar_retenidos()
        publisher.desconectar()
        subscriber.desconectar()
        print("[Shutdown] Mensajes retenidos eliminados del broker. Desconectado.")
        sys.exit(0)

    signal.signal(signal.SIGINT, salir)

    print(f"\n[Main] Simulacion activa — {NUM_CUARTOS} cuartos")
    print(
        "[Main] Frecuencia temperatura: "
        f"{INTERVALO_NORMAL_SEGUNDOS}s normal / {INTERVALO_ALARMA_SEGUNDOS}s en alarma"
    )
    print("[Main] El simulador publica: temperatura, presencia")
    print("[Main] El backend publica:   alarma, puerta, sei/sistema/estado\n")

    while True:
        ciclo += 1
        print(f"\n{'=' * 50}")
        print(f"  CICLO {ciclo}")
        print(f"{'=' * 50}")

        for n in range(1, NUM_CUARTOS + 1):
            ciclo_cuarto(n, cuartos[n], publisher)

        hay_alarma = any(
            cuartos[n]["alarma"].estado != "normal" for n in range(1, NUM_CUARTOS + 1)
        )
        intervalo = (
            INTERVALO_ALARMA_SEGUNDOS if hay_alarma else INTERVALO_NORMAL_SEGUNDOS
        )
        time.sleep(intervalo)


if __name__ == "__main__":
    main()
