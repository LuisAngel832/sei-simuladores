"""
SEI - Panel de control desechable
Overriders: hilos que republican periodicamente en topics estandar v3.0
con valores forzados.

Iteracion 1: OverrideTemperatura.
Iteracion 3: OverridePresencia.

Estrategia: como el simulador publica con retain=True (temperatura cada 30s,
presencia al cambio), republicar desde el panel a frecuencia mayor hace que el
broker entregue siempre el ultimo valor del panel a los suscriptores. Cuando el
panel detiene el override, el simulador retoma control en su siguiente ciclo.
"""
import threading
from datetime import datetime, timezone


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _calcular_estado_alarma(temperatura: float) -> str:
    """
    Misma logica que SensorTemperatura.leer() en sensores.py:
      < 3.0   -> normal
      3.0-4.0 -> preventiva
      > 4.0   -> critica
    """
    if temperatura < 3.0:
        return "normal"
    if temperatura <= 4.0:
        return "preventiva"
    return "critica"


class OverrideTemperatura(threading.Thread):
    """
    Republica sei/cuartos/{n}/temperatura con un valor forzado.

    Modos:
      'calentamiento' -> sube +0.5 C cada ciclo hasta target_celsius.
      'enfriamiento'  -> baja -0.5 C cada ciclo hasta target_celsius.
      'objetivo'      -> mantiene target_celsius fijo.

    Cuando alcanza target, sigue publicando el target (no termina). Asi el
    simulador no recupera el topic. Se detiene con stop().
    """

    INTERVALO_S = 2.0
    DELTA_CALENTAMIENTO = 0.5
    DELTA_ENFRIAMIENTO = -0.5
    RANGO_SENSOR = (-40.0, 20.0)

    def __init__(
        self,
        publisher,
        cuarto_id: int,
        modo: str,
        target_celsius: float,
        valor_inicial: float = -17.0,
    ):
        super().__init__(daemon=True, name=f"OverrideTemp-{cuarto_id}")
        self._publisher = publisher
        self._cuarto_id = cuarto_id
        self._modo = modo
        self._target = target_celsius
        self._valor_actual = valor_inicial
        self._stop_event = threading.Event()

    @property
    def cuarto_id(self) -> int:
        return self._cuarto_id

    @property
    def modo(self) -> str:
        return self._modo

    @property
    def target(self) -> float:
        return self._target

    @property
    def valor_actual(self) -> float:
        return self._valor_actual

    def stop(self):
        self._stop_event.set()

    def run(self):
        print(
            f"[OverrideTemp {self._cuarto_id}] Iniciando modo='{self._modo}' "
            f"target={self._target}C desde {self._valor_actual}C"
        )
        # Anuncia override activo para que el simulador deje de publicar
        # temperatura en este cuarto y no pise los valores forzados.
        self._publicar_control(active=True)
        try:
            while not self._stop_event.is_set():
                self._aplicar_paso()
                self._publicar()
                self._stop_event.wait(self.INTERVALO_S)
        finally:
            self._publicar_control(active=False)
        print(f"[OverrideTemp {self._cuarto_id}] Detenido")

    def _publicar_control(self, active: bool):
        payload = {
            "cuarto_id": self._cuarto_id,
            "active": active,
            "timestamp": _timestamp_now(),
        }
        if active:
            payload["modo"] = self._modo
            payload["target"] = self._target
        topic = f"sei/panel/override/temperatura/{self._cuarto_id}"
        self._publisher.publicar(topic, payload, qos=1, retain=True)

    def _aplicar_paso(self):
        if self._modo == "calentamiento":
            if self._valor_actual < self._target:
                self._valor_actual = round(
                    self._valor_actual + self.DELTA_CALENTAMIENTO, 2
                )
                if self._valor_actual > self._target:
                    self._valor_actual = self._target
        elif self._modo == "enfriamiento":
            if self._valor_actual > self._target:
                self._valor_actual = round(
                    self._valor_actual + self.DELTA_ENFRIAMIENTO, 2
                )
                if self._valor_actual < self._target:
                    self._valor_actual = self._target
        elif self._modo == "objetivo":
            self._valor_actual = self._target
        # Clamp al rango fisico del sensor
        self._valor_actual = max(
            self.RANGO_SENSOR[0], min(self.RANGO_SENSOR[1], self._valor_actual)
        )

    def _publicar(self):
        payload = {
            "cuarto_id": self._cuarto_id,
            "timestamp": _timestamp_now(),
            "temperatura": self._valor_actual,
            "unidad": "celsius",
            "estado_alarma": _calcular_estado_alarma(self._valor_actual),
            "origen": "simulador",
        }
        topic = f"sei/cuartos/{self._cuarto_id}/temperatura"
        self._publisher.publicar(topic, payload, qos=0, retain=True)


class OverridePresencia(threading.Thread):
    """
    Republica sei/cuartos/{n}/presencia con un valor forzado.

    Payload conforme al Contrato MQTT v3.0 seccion 4 y a sensores.py:
      cuarto_id, timestamp, presencia (bool), segundos_desde_ultimo_movimiento

    Cuando presencia=True, segundos_desde_ultimo_movimiento se mantiene en 0.
    Cuando presencia=False, el contador crece en cada ciclo (mismo cap 9999
    que SensorMovimiento del simulador).
    """

    INTERVALO_S = 5.0
    SEGUNDOS_INACTIVIDAD_INICIAL = 30
    CAP_SEGUNDOS_INACTIVIDAD = 9999

    def __init__(self, publisher, cuarto_id: int, presencia: bool):
        super().__init__(daemon=True, name=f"OverridePres-{cuarto_id}")
        self._publisher = publisher
        self._cuarto_id = cuarto_id
        self._presencia = presencia
        self._segundos_sin_movimiento = (
            0 if presencia else self.SEGUNDOS_INACTIVIDAD_INICIAL
        )
        self._stop_event = threading.Event()

    @property
    def cuarto_id(self) -> int:
        return self._cuarto_id

    @property
    def presencia(self) -> bool:
        return self._presencia

    @property
    def segundos_sin_movimiento(self) -> int:
        return self._segundos_sin_movimiento

    def stop(self):
        self._stop_event.set()

    def run(self):
        print(
            f"[OverridePres {self._cuarto_id}] Iniciando presencia={self._presencia}"
        )
        while not self._stop_event.is_set():
            self._publicar()
            if not self._presencia:
                self._segundos_sin_movimiento = min(
                    self._segundos_sin_movimiento + int(self.INTERVALO_S),
                    self.CAP_SEGUNDOS_INACTIVIDAD,
                )
            self._stop_event.wait(self.INTERVALO_S)
        print(f"[OverridePres {self._cuarto_id}] Detenido")

    def _publicar(self):
        payload = {
            "cuarto_id": self._cuarto_id,
            "timestamp": _timestamp_now(),
            "presencia": self._presencia,
            "segundos_desde_ultimo_movimiento": self._segundos_sin_movimiento,
        }
        topic = f"sei/cuartos/{self._cuarto_id}/presencia"
        self._publisher.publicar(topic, payload, qos=1, retain=True)
