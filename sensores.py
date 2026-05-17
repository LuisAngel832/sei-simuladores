"""
SEI - Sistema de Enfriamiento Inteligente
Módulo de sensores: emula condiciones físicas de cada cuarto.
"""
import os
import random
from datetime import datetime, timezone


# Amplitud del ruido aleatorio del sensor de temperatura, en grados Celsius.
# T-01-02 (Sprint 1) pide ±0.3 C como variación aleatoria por ciclo.
# Override por entorno con SEI_SIM_RUIDO si se quiere ajustar para demos.
RUIDO_AMPLITUD = float(os.getenv("SEI_SIM_RUIDO", "0.3"))


def timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SensorTemperatura:
    """
    Emula el sensor de temperatura de un cuarto frigorífico.
    Temperatura objetivo normal: entre -20 °C y -15 °C.
    Simula degradación lenta cuando la puerta está abierta.
    """

    TempObjetivoMin = -20.0
    TempObjetivoMax = -15.0
    Rango = (-40.0, 20.0)

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        
        self._temperatura = round(
            random.uniform(self.TempObjetivoMin, self.TempObjetivoMax), 2
        )
        self._deriva = 0.0  

    def set_deriva(self, delta: float):
        """
        Permite que los actuadores o la simulación ajusten la deriva.
        Positivo = calentamiento, negativo = enfriamiento.
        """
        self._deriva = delta

    def leer(self) -> dict:
        """
        Aplica la deriva y devuelve el payload del tópico temperatura.
        """
        # Variación aleatoria conforme a T-01-02 (Sprint 1): ±0.3 C por ciclo.
        ruido = random.uniform(-RUIDO_AMPLITUD, RUIDO_AMPLITUD)
        self._temperatura = round(self._temperatura + self._deriva + ruido, 2)
        # Clamp al rango válido del sensor
        self._temperatura = max(self.Rango[0],
                                min(self.Rango[1], self._temperatura))

        # Determina estado de alarma según temperatura
        if self._temperatura < 3.0:
            estado = "normal"
        elif self._temperatura <= 4.0:
            estado = "preventiva"
        else:
            estado = "critica"


        return {
            "cuarto_id": self.cuarto_id,
            "timestamp": timestamp_now(),
            "temperatura": self._temperatura,
            "unidad": "celsius",
            "estado_alarma": estado,
            "origen": "simulador",
        }

    @property
    def temperatura_actual(self) -> float:
        return self._temperatura


class SensorMovimiento:
    """
    Emula el sensor PIR de presencia humana en un cuarto frigorifico.

    Modelo de "visita" (SIM-01): la mayor parte del tiempo el cuarto esta
    en reposo (sin presencia). Esporadicamente se inicia una visita
    (carga/descarga) que dura unos pocos ciclos y luego termina, dejando
    el cuarto otra vez en reposo. Esto refleja el uso real: las puertas
    no permanecen abiertas continuamente, sino solo durante eventos de
    operacion discretos.

    Parametros override por env (utiles para acelerar pruebas):
      SEI_SIM_PROB_VISITA       (default 0.04 = 4 % por ciclo en reposo)
      SEI_SIM_VISITA_MIN_CICLOS (default 2  = ~60 s)
      SEI_SIM_VISITA_MAX_CICLOS (default 5  = ~150 s)
    """

    PROB_INICIAR_VISITA = float(os.getenv("SEI_SIM_PROB_VISITA", "0.04"))
    VISITA_MIN_CICLOS   = int(os.getenv("SEI_SIM_VISITA_MIN_CICLOS", "2"))
    VISITA_MAX_CICLOS   = int(os.getenv("SEI_SIM_VISITA_MAX_CICLOS", "5"))

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        self._presencia = False
        self._segundos_sin_movimiento = 999
        # Cuando > 0, la visita sigue activa por N ciclos mas
        self._ciclos_visita_restantes = 0

    def simular_evento(self):
        """
        Modelo de visitas discretas:
          - Si hay visita activa: decrementa ciclos restantes; al llegar
            a 0, finaliza la visita y la presencia vuelve a False.
          - Si no hay visita: con baja probabilidad (PROB_INICIAR_VISITA)
            inicia una nueva con duracion aleatoria entre MIN y MAX.
        """
        if self._ciclos_visita_restantes > 0:
            self._ciclos_visita_restantes -= 1
            self._presencia = True
            self._segundos_sin_movimiento = 0
            if self._ciclos_visita_restantes == 0:
                # La visita termino en este ciclo
                self._presencia = False
            return

        # Sin visita activa: ¿se inicia una nueva?
        if random.random() < self.PROB_INICIAR_VISITA:
            self._presencia = True
            self._ciclos_visita_restantes = random.randint(
                self.VISITA_MIN_CICLOS, self.VISITA_MAX_CICLOS
            ) - 1
            self._segundos_sin_movimiento = 0
        else:
            self._presencia = False
            self._segundos_sin_movimiento = min(
                self._segundos_sin_movimiento + 30, 9999
            )

    def leer(self) -> dict:
        """
        Devuelve el payload del tópico presencia.
        """
        self.simular_evento()
        return {
            "cuarto_id": self.cuarto_id,
            "timestamp": timestamp_now(),
            "presencia": self._presencia,
            "segundos_desde_ultimo_movimiento": self._segundos_sin_movimiento,
        }

    @property
    def hay_presencia(self) -> bool:
        return self._presencia
