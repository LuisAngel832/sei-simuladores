"""
SEI - Panel de control desechable
Listener de sei/sistema/seguridad (Contrato MQTT v3.0 seccion 5 paso 5).

Cuando el backend rechaza un comando por rol no autorizado o JWT invalido,
publica el intento en sei/sistema/seguridad. Este listener imprime esos
eventos en la consola del panel para depurar las pruebas:
  - CP-AUTH-01 (operador rechazado en silenciar/forzar*)
  - CP-AUTH-02 (JWT invalido o suplantado)
  - T-10-06    (jperez intenta forzar refrigeracion)
"""
import json
import os
import uuid

import paho.mqtt.client as mqtt


def _default_broker_host() -> str:
    return "192.168.1.100"


BROKER_HOST = os.getenv("MQTT_HOST", _default_broker_host())
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
KEEPALIVE = 60


class SecurityListener:
    """
    Cliente MQTT que solo escucha sei/sistema/seguridad e imprime los
    intentos rechazados por el backend.
    """

    TOPIC = "sei/sistema/seguridad"

    def __init__(self):
        client_id = f"sei-panel-sec-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def conectar(self):
        self.client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
        self.client.loop_start()

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(self.TOPIC, qos=1)
            print(f"[SecListener] [OK] Escuchando {self.TOPIC}")
        else:
            print(f"[SecListener] [ERROR] Codigo de conexion: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print(f"[SecListener] Desconectado (rc={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[SecListener] [WARN] Payload invalido en {msg.topic}: {exc}")
            return

        topic_intentado = payload.get("topic_intentado", "?")
        operador_id = payload.get("operador_id", "?")
        rol = payload.get("rol", "?")
        motivo = payload.get("motivo", payload.get("razon", "rol_no_autorizado"))
        timestamp = payload.get("timestamp", "?")
        print(
            f"[SecListener] [SEGURIDAD] {timestamp} | rechazo en {topic_intentado} "
            f"| operador_id={operador_id} rol={rol} motivo={motivo}"
        )
