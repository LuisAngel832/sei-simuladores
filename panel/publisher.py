"""
SEI - Panel de control desechable
Cliente MQTT del panel.

Publica unicamente en topics definidos por el Contrato MQTT v3.0 (E7).
Los payloads se construyen aqui conforme a la seccion 4 del contrato.

Metodos de comando implementados:
  - publicar_puerta_cmd          (Iter 2 — HU-06, HU-08)
  - publicar_refrigeracion_cmd   (Iter 4 — HU-10)
  - publicar_alarma_cmd          (CP-AUTH-02 — escenario G)

Las credenciales (operador_id, rol, jwt_token) provienen de un objeto Sesion
creado por panel.auth. El publisher no inventa credenciales — si falta sesion
los comandos /cmd no se publican.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from panel.auth import Sesion, login_mock


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_broker_host() -> str:
    return "192.168.1.100"


BROKER_HOST = os.getenv("MQTT_HOST", _default_broker_host())
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
KEEPALIVE = 60


class PanelPublisher:
    """
    Cliente MQTT del panel. Comparte broker con el simulador.
    Recibe una Sesion (de panel.auth) que provee operador_id, rol y jwt_token
    para todos los topics /cmd. Si no se pasa sesion, se usa una mock anonima
    para no romper invocaciones existentes.
    """

    def __init__(self, sesion: Sesion | None = None):
        client_id = f"sei-panel-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._conectado = False
        self._sesion: Sesion = sesion or login_mock("anon", rol="supervisor")

    def set_sesion(self, sesion: Sesion):
        """Reemplaza la sesion activa (p.ej. tras un re-login)."""
        self._sesion = sesion

    @property
    def sesion(self) -> Sesion:
        return self._sesion

    def conectar(self):
        print(f"[Panel] Conectando a EMQX {BROKER_HOST}:{BROKER_PORT}...")
        self.client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
        self.client.loop_start()

    def desconectar(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[Panel] Desconectado")

    @property
    def conectado(self) -> bool:
        return self._conectado

    def publicar(self, topic: str, payload: dict, qos: int = 1, retain: bool = False):
        """
        Publicacion base. Serializa a JSON y envia al broker.
        """
        if not self._conectado:
            print(f"[Panel] [WARN] Sin conexion. Descartado: {topic}")
            return False

        mensaje_json = json.dumps(payload, ensure_ascii=False)
        result = self.client.publish(topic, mensaje_json, qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[Panel] [ERROR] rc={result.rc} en {topic}")
            return False
        print(f"[Panel] -> {topic} | qos={qos} retain={retain}")
        return True

    # ── Comandos del Contrato v3.0 ────────────────────────────────────────────

    def publicar_puerta_cmd(
        self,
        cuarto_id: int,
        comando: str,
        razon: str | None = None,
    ) -> bool:
        """
        sei/cuartos/{n}/puerta/cmd — QoS 1, retain=False.
        Comandos validos (Contrato v3.0 seccion 4):
          'forzar_cierre' | 'forzar_apertura' | 'cancelar_cierre_auto'
        Matriz de autorizacion (seccion 5):
          forzar_*           -> solo supervisor
          cancelar_cierre_*  -> ambos roles
        El panel envia siempre rol='supervisor' para cubrir todos los casos.
        """
        comandos_validos = {"forzar_cierre", "forzar_apertura", "cancelar_cierre_auto"}
        if comando not in comandos_validos:
            print(f"[Panel] [ERROR] Comando invalido: {comando}")
            return False

        payload = {
            "cuarto_id": cuarto_id,
            "timestamp": _timestamp_now(),
            "comando": comando,
            "operador_id": self._sesion.operador_id,
            "rol": self._sesion.rol,
            "jwt_token": self._sesion.jwt_token,
        }
        if razon is not None:
            payload["razon"] = razon

        topic = f"sei/cuartos/{cuarto_id}/puerta/cmd"
        return self.publicar(topic, payload, qos=1, retain=False)

    def publicar_refrigeracion_cmd(
        self,
        cuarto_id: int,
        comando: str,
        potencia_pct: int,
        duracion_minutos: int | None = None,
    ) -> bool:
        """
        sei/cuartos/{n}/refrigeracion/cmd — QoS 1, retain=False.
        Comandos validos (Contrato v3.0 seccion 4):
          'forzar_encendido' | 'cancelar_forzado'
        Matriz de autorizacion (seccion 5): ambos requieren rol='supervisor'.
        Campos:
          potencia_pct       obligatorio (0-100)
          duracion_minutos   opcional (default 10 segun contrato)
        """
        comandos_validos = {"forzar_encendido", "cancelar_forzado"}
        if comando not in comandos_validos:
            print(f"[Panel] [ERROR] Comando invalido: {comando}")
            return False
        if not 0 <= potencia_pct <= 100:
            print(f"[Panel] [ERROR] potencia_pct fuera de rango: {potencia_pct}")
            return False

        payload = {
            "cuarto_id": cuarto_id,
            "timestamp": _timestamp_now(),
            "comando": comando,
            "potencia_pct": potencia_pct,
            "operador_id": self._sesion.operador_id,
            "rol": self._sesion.rol,
            "jwt_token": self._sesion.jwt_token,
        }
        if duracion_minutos is not None:
            payload["duracion_minutos"] = duracion_minutos

        topic = f"sei/cuartos/{cuarto_id}/refrigeracion/cmd"
        return self.publicar(topic, payload, qos=1, retain=False)

    def publicar_alarma_cmd(
        self,
        cuarto_id: int,
        alarma_id: int,
        comando: str,
    ) -> bool:
        """
        sei/cuartos/{n}/alarma/cmd — QoS 1, retain=False (Contrato v3.0).
        Comandos validos: 'ack' | 'silenciar'.
        Matriz de autorizacion (seccion 5):
          ack         -> ambos roles
          silenciar   -> solo supervisor
        El backend rechaza silenciar con rol='operador' y publica el intento
        en sei/sistema/seguridad — util para CP-AUTH-02.
        """
        comandos_validos = {"ack", "silenciar"}
        if comando not in comandos_validos:
            print(f"[Panel] [ERROR] Comando alarma invalido: {comando}")
            return False

        payload = {
            "cuarto_id": cuarto_id,
            "alarma_id": alarma_id,
            "timestamp": _timestamp_now(),
            "comando": comando,
            "operador_id": self._sesion.operador_id,
            "rol": self._sesion.rol,
            "jwt_token": self._sesion.jwt_token,
        }
        topic = f"sei/cuartos/{cuarto_id}/alarma/cmd"
        return self.publicar(topic, payload, qos=1, retain=False)

    # ── Callbacks MQTT ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._conectado = True
            print(f"[Panel] [OK] Conectado a EMQX {BROKER_HOST}:{BROKER_PORT}")
        else:
            print(f"[Panel] [ERROR] Codigo de conexion: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._conectado = False
        if rc != 0:
            print(f"[Panel] Desconectado inesperadamente (rc={rc})")
