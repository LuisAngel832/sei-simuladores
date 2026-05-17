"""
SEI - Sistema de Enfriamiento Inteligente
Publisher y Subscriber MQTT — Contrato v2.0 (broker EMQX)

Cambios respecto a v1.0:
  - Broker: EMQX 5.x en 192.168.1.100:1883 (en lugar de Mosquitto en localhost).
  - El simulador Python SOLO publica temperatura y presencia.
  - alarma, puerta y sei/sistema/estado los publica el Backend (Spring Boot).
  - El Subscriber ahora escucha los tópicos del backend (alarma, puerta,
    sei/sistema/estado) para sincronizar el estado interno de la simulación
    cuando el backend toma decisiones.
  - Los comandos puerta/cmd y refrigeracion/cmd van del HMI al Backend;
    el Subscriber los escucha para aplicar la lógica física en el simulador.

Responsabilidades por componente (contrato v2.0):
  Simulador Python  → publica: temperatura, presencia
  Backend (Spring)  → publica: alarma, puerta, sei/sistema/estado
  HMI (Node.js)     → publica: puerta/cmd, refrigeracion/cmd
"""

import json
import os
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


def timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_broker_host() -> str:
    """
    Host por defecto segun contrato MQTT E7 v3.0.
    """
    return "192.168.1.100"


# ── Configuración del broker EMQX (sección 2, contrato v2.0) ──────────────────
# Host: IP fija del Servidor SEI en la LAN.
# Puerto MQTT TCP: 1883 — sin cambio respecto a v1.0.
# Dashboard EMQX: http://192.168.1.100:18083 (admin / public) — solo monitoreo.

BROKER_HOST = os.getenv("MQTT_HOST", _default_broker_host())
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
KEEPALIVE = 60
BROKER_DASHBOARD_URL = os.getenv(
    "MQTT_DASHBOARD_URL", f"http://{BROKER_HOST}:18083"
)  # referencia informativa


class Publisher:
    """
    Publica ÚNICAMENTE los tópicos que le corresponden al simulador Python
    según el contrato v2.0:
      - sei/cuartos/{n}/temperatura  (QoS 0, retain=True)
      - sei/cuartos/{n}/presencia    (QoS 1, retain=True)

    Los tópicos alarma, puerta y sei/sistema/estado son responsabilidad
    del Backend (Spring Boot) — este Publisher NO los publica.

    Mantiene el estado compartido `cuartos` para que los actuadores
    puedan leer temperatura y presencia actuales al componer su lógica interna.
    """

    def __init__(self):
        client_id = f"sei-simulador-pub-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # Estado compartido: temperatura y presencia actuales por cuarto.
        # alarma y puerta los actualiza el Subscriber cuando llegan del backend.
        self.cuartos: dict = {
            n: {
                "temperatura": -17.0,
                "presencia": False,
                "alarma": "normal",  # sincronizado desde backend vía Subscriber
                "puerta": "cerrada",  # sincronizado desde backend vía Subscriber
            }
            for n in range(1, 6)
        }

        # Indica por cuarto si el panel tiene un override de temperatura activo.
        # Mientras esté True el simulador no publica para ese cuarto y deja
        # que el panel sea la única fuente — evita la condición de carrera
        # donde el simulador publicaba cada 5–30 s y pisaba el valor forzado.
        self.panel_overrides_temp: dict = {n: False for n in range(1, 6)}

        self._conectado = False

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    def conectar(self):
        self.client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
        self.client.loop_start()

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()

    # ── Limpieza de retained ───────────────────────────────────────────────────

    def limpiar_retenidos(self):
        """
        Borra los mensajes retained del simulador antes de desconectar.

        EMQX conserva el último mensaje publicado con retain=True por topic;
        cuando el HMI reconecta tras un apagado del simulador, recibe esos
        valores viejos como si fueran actuales. Para borrarlos basta con
        publicar un payload vacío (b"") con retain=True en cada topic.

        Solo se limpian los topics del simulador (temperatura y presencia
        de cuartos 1..5). Los topics de puerta, alarma, refrigeracion y
        sei/sistema/estado son responsabilidad del Backend.
        """
        if not self._conectado:
            print(
                "[Publisher] [WARN] Sin conexion al broker; "
                "no se pueden limpiar mensajes retenidos."
            )
            return

        topics_a_limpiar = []
        for n in range(1, 6):
            topics_a_limpiar.append(f"sei/cuartos/{n}/temperatura")
            topics_a_limpiar.append(f"sei/cuartos/{n}/presencia")

        limpiados = 0
        for topic in topics_a_limpiar:
            try:
                info = self.client.publish(topic, payload=b"", qos=1, retain=True)
                # wait_for_publish bloquea hasta que el broker confirme el QoS 1
                # (PUBACK). Timeout corto para no colgar el shutdown si el broker
                # esta degradado o caido a medio camino.
                info.wait_for_publish(timeout=2)
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    limpiados += 1
                else:
                    print(
                        f"[Publisher] [WARN] No se pudo limpiar '{topic}': rc={info.rc}"
                    )
            except (ValueError, RuntimeError) as e:
                # ValueError: cliente desconectado durante el wait
                # RuntimeError: timeout u otro fallo de paho
                print(f"[Publisher] [WARN] Error limpiando '{topic}': {e}")

        print(
            f"[Publisher] Limpiados {limpiados} topics retained antes de desconectar"
        )

    # ── Publicación base ───────────────────────────────────────────────────────

    def publicar(self, topic: str, payload: dict, qos: int = 0, retain: bool = False):
        """
        Serializa el payload a JSON y lo publica en el broker EMQX.
        Único punto de salida de mensajes del simulador.
        """
        if not self._conectado:
            print(
                f"[Publisher] [WARN] Sin conexion a {BROKER_HOST}. Descartado: {topic}"
            )
            return

        mensaje_json = json.dumps(payload, ensure_ascii=False)
        result = self.client.publish(topic, mensaje_json, qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[Publisher] [ERROR] Error publicando en {topic}: rc={result.rc}")

    # ── Tópicos del simulador (contrato v2.0, sección 4) ──────────────────────

    def publicar_temperatura(self, payload: dict):
        """
        sei/cuartos/{n}/temperatura — QoS 0, retain=True.
        Publicador: Simulador Python (contrato v2.0).
        Suscriptores: MqttListenerThread (Spring Boot), Node.js HMI.
        Actualiza el estado interno de temperatura del cuarto.
        """
        cid = payload["cuarto_id"]
        self.cuartos[cid]["temperatura"] = payload["temperatura"]
        topic = f"sei/cuartos/{cid}/temperatura"
        self.publicar(topic, payload, qos=0, retain=True)

    def publicar_presencia(self, payload: dict):
        """
        sei/cuartos/{n}/presencia — QoS 1, retain=True.
        Publicador: Simulador Python (contrato v2.0).
        Suscriptores: MqttListenerThread (Spring Boot), Node.js HMI.
        QoS 1 porque este dato es crítico para el cierre automático de puertas.
        Actualiza el estado interno de presencia del cuarto.
        """
        cid = payload["cuarto_id"]
        self.cuartos[cid]["presencia"] = payload["presencia"]
        topic = f"sei/cuartos/{cid}/presencia"
        self.publicar(topic, payload, qos=1, retain=True)

    # ── Callbacks MQTT ─────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._conectado = True
            print(f"[Publisher] [OK] Conectado a EMQX {BROKER_HOST}:{BROKER_PORT}")
            print(f"[Publisher]   Dashboard: {BROKER_DASHBOARD_URL}")
        else:
            print(f"[Publisher] [ERROR] Error de conexion EMQX, codigo: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._conectado = False
        print(f"[Publisher] Desconectado de EMQX (rc={rc})")


class Subscriber:
    """
    Suscriptor MQTT del simulador — contrato v2.0.

    Escucha dos grupos de tópicos:

    GRUPO A — Decisiones del Backend (Spring Boot):
      sei/cuartos/+/alarma          → Sincroniza estado de alarma en publisher.cuartos
      sei/cuartos/+/puerta          → Sincroniza estado de puerta + despacha a Puerta
      sei/sistema/estado            → Logging del estado global

    GRUPO B — Comandos del HMI destinados al Backend:
      sei/cuartos/+/puerta/cmd       → Backend procesa; simulador aplica efecto físico
      sei/cuartos/+/refrigeracion/cmd → Backend procesa; simulador ajusta Enfriador

    Por qué el simulador escucha los comandos del HMI si van al Backend:
      El simulador necesita reflejar físicamente las decisiones (abrir/cerrar puerta,
      forzar enfriador) para que los sensores evolucionen de manera coherente.
      El Backend publica el estado de puerta resultante en sei/cuartos/{n}/puerta,
      pero el simulador también aplica el efecto directo en sus actuadores internos
      para no depender del round-trip Backend → broker → simulador en cada ciclo.
    """

    def __init__(self, publisher, actuadores_por_cuarto: dict):
        """
        publisher:              instancia de Publisher (para sincronizar cuartos[])
        actuadores_por_cuarto:  { cuarto_id: { "puerta": Puerta, "enfriador": Enfriador } }
        """
        self._publisher = publisher
        self._actuadores = actuadores_por_cuarto

        client_id = f"sei-simulador-sub-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    def conectar(self):
        self.client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
        self.client.loop_start()

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()

    # ── Callbacks MQTT ─────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[Subscriber] [OK] Conectado a EMQX {BROKER_HOST}:{BROKER_PORT}")

            # Grupo A: decisiones del Backend
            client.subscribe("sei/cuartos/+/alarma", qos=1)
            client.subscribe("sei/cuartos/+/puerta", qos=1)
            client.subscribe("sei/sistema/estado", qos=1)

            # Grupo B: comandos HMI → Backend (el simulador también reacciona)
            client.subscribe("sei/cuartos/+/puerta/cmd", qos=1)
            client.subscribe("sei/cuartos/+/refrigeracion/cmd", qos=1)

            # Grupo C: temperatura republicada (panel u otro emisor) — para
            # mantener publisher.cuartos[n]["temperatura"] sincronizado con
            # el valor real del broker y evitar saltos al detener overrides.
            client.subscribe("sei/cuartos/+/temperatura", qos=0)

            # Grupo D: control del panel — anuncia overrides activos para
            # que el simulador deje de publicar temperatura en ese cuarto.
            client.subscribe("sei/panel/override/temperatura/+", qos=1)

            print("[Subscriber] Suscripciones activas:")
            print("  Grupo A (backend) → sei/cuartos/+/alarma")
            print("                    → sei/cuartos/+/puerta")
            print("                    → sei/sistema/estado")
            print("  Grupo B (cmds)    → sei/cuartos/+/puerta/cmd")
            print("                    → sei/cuartos/+/refrigeracion/cmd")
            print("  Grupo C (temp)    → sei/cuartos/+/temperatura")
            print("  Grupo D (panel)   → sei/panel/override/temperatura/+")
        else:
            print(f"[Subscriber] [ERROR] Error de conexion EMQX, codigo: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        print(f"[Subscriber] Desconectado de EMQX (rc={rc})")

    def _on_message(self, client, userdata, msg):
        """
        Router central de mensajes entrantes.
        1. Valida JSON (sección 6 del contrato).
        2. Extrae cuarto_id y valida rango.
        3. Despacha según patrón de tópico.
        """
        topic = msg.topic

        # ── 1. Validación JSON ─────────────────────────────────────────────────
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[Subscriber] [ERROR] JSON invalido en '{topic}': {e}")
            return

        partes = topic.split("/")  # ej. ['sei','cuartos','3','puerta','cmd']

        # ── sei/sistema/estado (sin cuarto_id) ─────────────────────────────────
        if topic == "sei/sistema/estado":
            self._handle_estado_sistema(payload)
            return

        # ── sei/panel/override/temperatura/{n} ─────────────────────────────────
        # Se evalúa antes que el filtro de cuartos porque rompe el patrón
        # 'sei/cuartos/...' que asume el resto del router.
        if (
            len(partes) == 5
            and partes[0] == "sei"
            and partes[1] == "panel"
            and partes[2] == "override"
            and partes[3] == "temperatura"
        ):
            self._handle_panel_override_temp(partes[4], payload)
            return

        # ── Tópicos de cuarto — extraer y validar cuarto_id ────────────────────
        if len(partes) < 4 or partes[0] != "sei" or partes[1] != "cuartos":
            return

        try:
            cuarto_id = int(partes[2])
        except ValueError:
            print(f"[Subscriber] [ERROR] cuarto_id no numerico en: {topic}")
            return

        if not (1 <= cuarto_id <= 5):
            print(
                f"[Subscriber] [ERROR] cuarto_id fuera de rango [{cuarto_id}] en: {topic}"
            )
            return

        actuadores = self._actuadores.get(cuarto_id, {})
        categoria = partes[3] if len(partes) > 3 else ""
        accion = partes[4] if len(partes) > 4 else ""

        # ── GRUPO A: mensajes del backend ──────────────────────────────────────

        # sei/cuartos/{n}/alarma  → sincronizar estado en publisher.cuartos
        if categoria == "alarma" and accion == "":
            self._handle_alarma(cuarto_id, payload)

        # sei/cuartos/{n}/puerta  → sincronizar estado + notificar actuador Puerta
        elif categoria == "puerta" and accion == "":
            self._handle_puerta(cuarto_id, payload, actuadores)

        # sei/cuartos/{n}/temperatura → solo refresca el cache compartido
        # para que main.py pueda leer el último valor publicado por el panel
        # mientras dura un override y resincronizar el sensor al detenerse.
        elif categoria == "temperatura" and accion == "":
            self._handle_temperatura(cuarto_id, payload)

        # ── GRUPO B: comandos del HMI ──────────────────────────────────────────

        # sei/cuartos/{n}/puerta/cmd  → aplicar en actuador Puerta
        elif categoria == "puerta" and accion == "cmd":
            self._handle_puerta_cmd(cuarto_id, payload, actuadores)

        # sei/cuartos/{n}/refrigeracion/cmd → aplicar en actuador Enfriador
        elif categoria == "refrigeracion" and accion == "cmd":
            self._handle_refrigeracion_cmd(cuarto_id, payload, actuadores)

    # ── Handlers específicos ───────────────────────────────────────────────────

    def _handle_estado_sistema(self, payload: dict):
        """
        sei/sistema/estado — publicado por el Backend (Spring Boot).
        Sincroniza el estado global de todos los cuartos en publisher.cuartos.
        Útil al arrancar el simulador si el backend ya estaba corriendo.
        """
        cuartos_backend = payload.get("cuartos", [])
        alarmas_activas = 0
        for c in cuartos_backend:
            cid = c.get("id")
            if cid and 1 <= cid <= 5:
                self._publisher.cuartos[cid]["alarma"] = c.get("alarma", "normal")
                self._publisher.cuartos[cid]["puerta"] = c.get("puerta", "cerrada")
                if c.get("alarma") != "normal":
                    alarmas_activas += 1
        print(
            f"[Subscriber] Estado sistema recibido @ {payload.get('timestamp', '?')} "
            f"| Cuartos con alarma: {alarmas_activas}"
        )

    def _handle_alarma(self, cuarto_id: int, payload: dict):
        """
        sei/cuartos/{n}/alarma — publicado por el Backend (Spring Boot).
        Sincroniza el estado de alarma en el estado compartido del Publisher.
        El simulador usa este valor para ajustar la frecuencia de muestreo
        y para la lógica interna de la Alarma local.
        """
        estado = payload.get("estado", "normal")
        self._publisher.cuartos[cuarto_id]["alarma"] = estado
        iconos = {"normal": "OK", "preventiva": "WARN", "critica": "CRIT"}
        print(
            f"[Subscriber] Alarma cuarto {cuarto_id}: "
            f"{iconos.get(estado, '?')} {estado} "
            f"| ID: {payload.get('alarma_id', '?')}"
        )

    def _handle_puerta(self, cuarto_id: int, payload: dict, actuadores: dict):
        """
        sei/cuartos/{n}/puerta — publicado por el Backend (Spring Boot).
        Sincroniza el estado de la puerta en publisher.cuartos y notifica
        al actuador Puerta local para que la CortinaDeAire reaccione
        y el sensor de temperatura evolucione correctamente.
        """
        estado = payload.get("estado", "cerrada")
        self._publisher.cuartos[cuarto_id]["puerta"] = estado

        puerta = actuadores.get("puerta")
        if puerta:
            # Notifica al actuador para que actualice su estado interno
            # sin volver a publicar (la publicación ya la hizo el backend)
            puerta.sincronizar_estado_backend(estado)

        print(
            f"[Subscriber] Puerta cuarto {cuarto_id}: "
            f"{estado} | Origen: {payload.get('origen', '?')}"
        )

    def _handle_puerta_cmd(self, cuarto_id: int, payload: dict, actuadores: dict):
        """
        sei/cuartos/{n}/puerta/cmd — publicado por el HMI (Node.js).
        El backend procesará este comando y publicará el resultado en
        sei/cuartos/{n}/puerta. El simulador también lo aplica localmente
        para que los sensores reflejen el efecto sin esperar el round-trip.
        """
        puerta = actuadores.get("puerta")
        if puerta:
            cmd = payload.get("comando", "?")
            print(
                f"[Subscriber] Cmd puerta cuarto {cuarto_id}: {cmd} "
                f"| Operador: {payload.get('operador_id', '?')}"
            )
            puerta.aplicar_comando(payload)

    def _handle_refrigeracion_cmd(
        self, cuarto_id: int, payload: dict, actuadores: dict
    ):
        """
        sei/cuartos/{n}/refrigeracion/cmd — publicado por el HMI (Node.js).
        El backend procesa el comando; el simulador ajusta el Enfriador
        local para que la temperatura evolucione de forma consistente.
        """
        enfriador = actuadores.get("enfriador")
        if enfriador:
            cmd = payload.get("comando", "?")
            print(
                f"[Subscriber] Cmd enfriador cuarto {cuarto_id}: {cmd} "
                f"| Potencia: {payload.get('potencia_pct', '?')}%"
            )
            enfriador.aplicar_comando(payload)

    def _handle_temperatura(self, cuarto_id: int, payload: dict):
        """
        sei/cuartos/{n}/temperatura — refresca el cache compartido con la
        temperatura observada en el broker (incluye lo publicado por el panel).
        """
        temp = payload.get("temperatura")
        if isinstance(temp, (int, float)):
            self._publisher.cuartos[cuarto_id]["temperatura"] = float(temp)

    def _handle_panel_override_temp(self, cuarto_str: str, payload: dict):
        """
        sei/panel/override/temperatura/{n} — el panel anuncia que tomó el
        control de temperatura del cuarto. Mientras active=True el simulador
        deja de publicar para ese cuarto.
        """
        try:
            cuarto_id = int(cuarto_str)
        except ValueError:
            print(f"[Subscriber] [ERROR] cuarto_id no numerico en panel override: {cuarto_str}")
            return
        if not (1 <= cuarto_id <= 5):
            print(f"[Subscriber] [ERROR] cuarto_id fuera de rango en panel override: {cuarto_id}")
            return
        active = bool(payload.get("active", False))
        self._publisher.panel_overrides_temp[cuarto_id] = active
        estado = "ON" if active else "OFF"
        print(f"[Subscriber] Panel override temp cuarto {cuarto_id}: {estado}")
