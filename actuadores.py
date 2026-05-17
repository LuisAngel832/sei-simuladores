"""
SEI - Sistema de Enfriamiento Inteligente
Módulo de actuadores — Contrato v2.0

Responsabilidades según contrato v2.0:
  Simulador Python  → publica: temperatura, presencia
  Backend (Spring)  → publica: alarma, puerta, sei/sistema/estado
  HMI (Node.js)     → publica: puerta/cmd, refrigeracion/cmd

Los actuadores de este módulo ya NO publican directamente en MQTT.
Solo mantienen estado interno que el simulador usa para:
  - Calcular derivas térmicas (CortinaAire, Enfriador)
  - Tomar decisiones de lógica automática (Puerta)
  - Registrar el estado de alarma local (Alarma)
El Subscriber sincroniza el estado de Puerta y Alarma cuando
el backend publica sus decisiones en el broker.
"""
from datetime import datetime, timezone


def timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Puerta:
    """
    Actuador de puerta del cuarto frigorífico — contrato v2.0.

    En v2.0 el Backend (Spring Boot) es quien publica en sei/cuartos/{n}/puerta.
    Este actuador:
      a) sincronizar_estado_backend(estado): llamado por el Subscriber cuando
         el backend publica un nuevo estado de puerta. Actualiza _estado sin publicar.
      b) aplicar_comando(payload): aplica el efecto físico local cuando llega un
         comando del HMI (puerta/cmd). El backend también procesará el comando y
         publicará el resultado; aquí lo aplicamos de forma local e inmediata para
         que la simulación no dependa del round-trip.
      c) evaluar_condiciones(): lógica de cierre automático local del simulador.
         En producción esta decisión la toma el backend.
    """

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        self._estado = "cerrada"

    # ── Sincronización desde el backend ───────────────────────────────────────

    def sincronizar_estado_backend(self, estado: str):
        """
        Actualiza el estado interno con la decisión del backend.
        No publica nada — la publicación ya la hizo el backend.
        """
        estados_validos = {"abierta", "cerrada", "cerrando", "cierre_cancelado"}
        if estado not in estados_validos:
            print(f"[Puerta {self.cuarto_id}] Estado invalido del backend: {estado}")
            return
        self._estado = estado
        print(f"[Puerta {self.cuarto_id}] Sincronizado desde backend -> {self._estado}")

    # ── Comando del HMI (efecto físico local) ─────────────────────────────────

    def aplicar_comando(self, payload: dict):
        """
        Aplica localmente el efecto del comando HMI.
        Comandos: forzar_cierre | forzar_apertura | cancelar_cierre_auto
        """
        cmd = payload.get("comando")
        if cmd == "forzar_cierre":
            self._estado = "cerrada"
        elif cmd == "forzar_apertura":
            self._estado = "abierta"
        elif cmd == "cancelar_cierre_auto":
            self._estado = "cierre_cancelado"
        else:
            print(f"[Puerta {self.cuarto_id}] Comando desconocido: {cmd}")
            return
        print(f"[Puerta {self.cuarto_id}] Efecto local '{cmd}' -> {self._estado}")

    # ── Lógica automática local ────────────────────────────────────────────────

    def evaluar_condiciones(self, hay_presencia: bool, temperatura: float):
        """
        Lógica de cierre automático del simulador (sin publicar).
        En producción esta decisión la toma el MqttListenerThread del backend.
        """
        if self._estado == "abierta":
            if not hay_presencia:
                self._estado = "cerrada"
                print(f"[Puerta {self.cuarto_id}] Cierre automatico local (sin presencia)")
            elif temperatura > 3.0:
                print(
                    f"[Puerta {self.cuarto_id}] Temp critica con presencia "
                    "- el backend debe decidir"
                )

    @property
    def estado(self) -> str:
        return self._estado


class CortinaDeAire:
    """
    Actuador de cortina de aire.
    Se activa cuando la puerta está abierta para frenar el calentamiento.
    No tiene tópico MQTT propio — es interno al simulador.
    """

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        self._activa = False

    def sincronizar_con_puerta(self, estado_puerta: str):
        nueva = estado_puerta == "abierta"
        if nueva != self._activa:
            self._activa = nueva
            print(
                f"[CortinaAire {self.cuarto_id}] "
                f"-> {'ENCENDIDA' if self._activa else 'APAGADA'}"
            )

    @property
    def activa(self) -> bool:
        return self._activa

    def influencia_termica(self) -> float:
        """Deriva térmica por ciclo cuando la cortina está activa (+0.06 C/ciclo)."""
        return 0.06 if self._activa else 0.0


class Enfriador:
    """
    Sistema de refrigeración independiente de cada cuarto — contrato v2.0.

    Reacciona a sei/cuartos/{n}/refrigeracion/cmd (HMI -> Backend -> simulador)
    y a lógica automática local.
    No publica en MQTT — solo ajusta su estado para que influencia_termica()
    modifique la deriva del sensor de temperatura.
    """

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        self._encendido = False
        self._potencia_pct = 0
        self._forzado = False
        self._ciclos_forzado = 0
        self._duracion_forzado_ciclos = 0

    def aplicar_comando(self, payload: dict):
        """
        Comandos: forzar_encendido | cancelar_forzado
        """
        cmd = payload.get("comando")
        if cmd == "forzar_encendido":
            potencia = payload.get("potencia_pct", 100)
            duracion = payload.get("duracion_minutos", 10)
            self._forzar_encendido(potencia, duracion)
        elif cmd == "cancelar_forzado":
            self._cancelar_forzado()
        else:
            print(f"[Enfriador {self.cuarto_id}] Comando desconocido: {cmd}")

    def evaluar_temperatura(self, temperatura: float):
        """
        Control automático:
          Enciende al 75% si temperatura > -15 C
          Apaga si temperatura < -18 C
        El forzado tiene prioridad sobre el automático.
        """
        if self._forzado:
            self._ciclos_forzado += 1
            if self._ciclos_forzado >= self._duracion_forzado_ciclos:
                self._cancelar_forzado()
            return

        if temperatura > -15.0 and not self._encendido:
            self._encender(potencia=75, origen="automatico")
        elif temperatura < -18.0 and self._encendido:
            self._apagar(origen="automatico")

    def _forzar_encendido(self, potencia: int, duracion_minutos: int):
        self._forzado = True
        self._ciclos_forzado = 0
        self._duracion_forzado_ciclos = duracion_minutos * 2  # 1 ciclo ~ 30 s
        self._encender(potencia, origen="forzado")

    def _cancelar_forzado(self):
        self._forzado = False
        self._ciclos_forzado = 0
        print(f"[Enfriador {self.cuarto_id}] Forzado completado, modo automatico")
        self._apagar(origen="automatico")

    def _encender(self, potencia: int, origen: str):
        self._encendido = True
        self._potencia_pct = potencia
        print(f"[Enfriador {self.cuarto_id}] ENCENDIDO al {potencia}% ({origen})")

    def _apagar(self, origen: str):
        self._encendido = False
        self._potencia_pct = 0
        print(f"[Enfriador {self.cuarto_id}] APAGADO ({origen})")

    def influencia_termica(self) -> float:
        """Potencia maxima: -0.20 C/ciclo."""
        if self._encendido:
            return -(self._potencia_pct / 100.0) * 0.20
        return 0.0


class Alarma:
    """
    Detector de alarma local del simulador — contrato v2.0.

    En v2.0 el Backend (Spring Boot) es quien publica en sei/cuartos/{n}/alarma.
    Esta clase:
      - evaluar(temperatura): determina el estado de alarma local y lo registra.
        NO publica — eso lo hace el backend cuando recibe la lectura de temperatura.
      - sincronizar_estado_backend(estado, alarma_id): llamado por el Subscriber
        cuando el backend publica en sei/cuartos/{n}/alarma.
    El estado local se usa para ajustar la frecuencia de muestreo del sensor
    (cada 30 s en normal, cada 5 s en alarma activa — contrato sección 4).
    """

    def __init__(self, cuarto_id: int):
        self.cuarto_id = cuarto_id
        self._estado_local = "normal"   # calculado localmente
        self._estado_backend = "normal" # confirmado por el backend
        self._temp_pico = -999.0
        self._alarma_id = 0

    def evaluar(self, temperatura: float) -> bool:
        """
        Calcula el estado de alarma y registra si hay cambio.
        Devuelve True si el estado cambió (el main.py puede usar esto
        para ajustar la frecuencia de lectura).
        """
        if temperatura < 3.0:
            nuevo = "normal"
        elif temperatura <= 4.0:
            nuevo = "preventiva"
        else:
            nuevo = "critica"

        if temperatura > self._temp_pico:
            self._temp_pico = temperatura

        if nuevo != self._estado_local:
            self._estado_local = nuevo
            iconos = {"normal": "[OK]", "preventiva": "[!!]", "critica": "[!!!!!]"}
            print(
                f"[Alarma {self.cuarto_id}] {iconos.get(nuevo,'?')} "
                f"Local -> {nuevo} | Temp: {temperatura:.2f}C "
                f"| Pico: {self._temp_pico:.2f}C"
            )
            return True
        return False

    def sincronizar_estado_backend(self, estado: str, alarma_id: int):
        """
        Actualiza el estado confirmado por el backend.
        Llamado por el Subscriber al recibir sei/cuartos/{n}/alarma.
        """
        self._estado_backend = estado
        self._alarma_id = alarma_id

    @property
    def estado(self) -> str:
        """Estado local calculado por el simulador."""
        return self._estado_local

    @property
    def estado_backend(self) -> str:
        """Estado confirmado por el backend."""
        return self._estado_backend

    @property
    def en_alarma(self) -> bool:
        """True si hay alarma activa (preventiva o critica)."""
        return self._estado_local != "normal"
