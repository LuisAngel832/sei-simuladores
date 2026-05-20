"""
SEI - Panel de control desechable
CLI interactivo basado en input().

Uso:
  cd files2
  python -m panel.cli

Iteracion 1: control de temperatura (HU-04, HU-05).
"""
import getpass
import signal
import sys
import time

from panel import auth, escenarios, operaciones
from panel.auth import Sesion
from panel.publisher import BROKER_HOST, BROKER_PORT, PanelPublisher
from panel.overrider import OverridePresencia, OverrideTemperatura
from panel.security_listener import SecurityListener


# Estado del CLI: overrides activos por cuarto
_overrides_temp: dict = {}  # {cuarto_id: OverrideTemperatura}
_overrides_presencia: dict = {}  # {cuarto_id: OverridePresencia}

# Modo de menu: False = Demo (5 min, solo escenarios de la presentacion),
# True = Avanzado (menu completo con comandos atomicos y escenarios A-G).
_modo_avanzado: bool = False


def _imprimir_titulo():
    print()
    print("=" * 60)
    print("   SEI - Panel de control desechable")
    print(f"   Broker EMQX: {BROKER_HOST}:{BROKER_PORT}")
    print("=" * 60)


def _prompt_sesion() -> Sesion:
    """
    Prompt de autenticacion al arranque. Pide usuario y password, hace
    POST /api/login real (panel.auth.login) con fallback a sesion mock.
    Sugiere jperez (operador) o cruiz (supervisor/auditor); el usuario
    puede escribir cualquier otro nombre.
    """
    print()
    print("  Autenticacion (POST /api/login con fallback a mock):")
    usuario = input("    Usuario [jperez/cruiz]> ").strip()
    if not usuario:
        usuario = "cruiz"
        print(f"    (vacio -> usando '{usuario}')")
    try:
        password = getpass.getpass("    Password> ")
    except (EOFError, KeyboardInterrupt):
        print()
        password = ""

    rol_fallback = "operador" if usuario.lower() == "jperez" else "supervisor"
    sesion = auth.login(usuario, password, rol_fallback=rol_fallback)
    print(f"  Sesion activa: {sesion}")
    print()
    return sesion


def _imprimir_menu_demo():
    """
    Menu reducido para la demo de 5 minutos. Alineado con el speech:
    un escenario integrador para el operador y otro para el supervisor.
    """
    print()
    print("--- Menu Demo (5 min) ---")
    print()
    print("  1) DEMO OPERADOR   - Descarga -> alarma -> desalojo ->")
    print("                       cierre auto -> refuerzo (requiere jperez)")
    print("  2) DEMO SUPERVISOR - Auditoria solo lectura + intento")
    print("                       rechazado (requiere cruiz)")
    print("  38) Reset          - Estado limpio (D6)")
    print()
    print("  90) Re-login (cambiar usuario/rol activo)")
    print("  99) Cambiar a menu Avanzado")
    print("   0) Salir")
    print()


def _imprimir_menu_avanzado():
    print()
    print("--- Menu Avanzado ---")
    print()
    print("  TEMPERATURA (Iter 1 - HU-04, HU-05)")
    print("   1) Calentar cuarto N hasta X C")
    print("   2) Enfriar cuarto N hasta X C")
    print("   3) Mantener cuarto N en X C (modo objetivo)")
    print("   4) Detener override de temperatura de cuarto N")
    print("   5) Listar overrides activos")
    print()
    print("  PUERTA (Iter 2 - HU-06, HU-08)")
    print("   6) Forzar apertura de puerta cuarto N")
    print("   7) Forzar cierre de puerta cuarto N")
    print("   8) Cancelar cierre automatico cuarto N")
    print()
    print("  PRESENCIA (Iter 3 - HU-03, HU-07)")
    print("   9) Forzar presencia ON cuarto N")
    print("  10) Forzar presencia OFF cuarto N")
    print("  11) Detener override de presencia cuarto N")
    print()
    print("  REFRIGERACION (Iter 4 - HU-10)")
    print("  12) Forzar encendido refrigeracion cuarto N al X% por Y min")
    print("  13) Cancelar forzado de refrigeracion cuarto N")
    print()
    print("  ESCENARIOS PRE-ARMADOS (Iter 5 - CP-SYS-01)")
    print("  14) A) Escalada de alarma (HU-04, HU-05)")
    print("  15) B) Cierre automatico sin presencia (HU-07)")
    print("  16) C) Cancelacion de cierre por presencia (HU-07)")
    print("  17) D) Apertura, cortina y potencia (HU-06, HU-08)")
    print("  18) E) Forzar refrigeracion (HU-10)")
    print("  19) F) CP-SYS-01 completo (orquesta A-E con pausas)")
    print("  20) G) Operador intenta silenciar (CP-AUTH-02)")
    print()
    print("  OPERACIONES DE NEGOCIO (Iter 6 - demo time-based)")
    print("  30) D3) Estado estable (baseline)")
    print("  31) D1) Descarga de producto (con variantes carga/boost)")
    print("  32) D4) Puerta olvidada -> cierre automatico")
    print("  33) D7) Reentrada cancela cierre")
    print("  34) D11) Forzar refrigeracion manual")
    print("  35) D12) Silenciar alarma critica")
    print("  36) D13) Auditor intenta comando (rechazo)")
    print("  37) D15) Caida de telemetria (timeout HMI)")
    print("  38) D6) Reset a estado limpio (todos los cuartos)")
    print()
    print("  90) Re-login (cambiar usuario/rol activo)")
    print("  99) Volver a menu Demo")
    print("  0) Salir")
    print()


def _imprimir_sesion(publisher: PanelPublisher):
    s = publisher.sesion
    print(
        f"  Sesion activa: {s} | operador_id={s.operador_id} "
        f"{'(JWT mock)' if s.es_mock else '(JWT real)'}"
    )


def _leer_opcion() -> str:
    try:
        return input("Opcion> ").strip()
    except EOFError:
        return "0"


def _leer_cuarto_id() -> int | None:
    try:
        valor = input("  Cuarto (1-5)> ").strip()
        cid = int(valor)
        if not 1 <= cid <= 5:
            print(f"  [ERROR] cuarto_id fuera de rango: {cid}")
            return None
        return cid
    except ValueError:
        print("  [ERROR] cuarto_id debe ser entero")
        return None


def _leer_temperatura() -> float | None:
    try:
        valor = input("  Temperatura objetivo (C)> ").strip()
        temp = float(valor)
        if not -40.0 <= temp <= 20.0:
            print(f"  [ERROR] temperatura fuera de rango sensor: {temp}")
            return None
        return temp
    except ValueError:
        print("  [ERROR] temperatura debe ser numero")
        return None


def _iniciar_override(publisher, modo: str):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    target = _leer_temperatura()
    if target is None:
        return

    if cuarto_id in _overrides_temp:
        print(f"  [WARN] Ya hay override activo en cuarto {cuarto_id}, deteniendo previo")
        _overrides_temp[cuarto_id].stop()
        _overrides_temp[cuarto_id].join(timeout=3.0)

    override = OverrideTemperatura(
        publisher=publisher,
        cuarto_id=cuarto_id,
        modo=modo,
        target_celsius=target,
    )
    override.start()
    _overrides_temp[cuarto_id] = override
    print(f"  [OK] Override '{modo}' iniciado en cuarto {cuarto_id} -> {target} C")


def _detener_override():
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    override = _overrides_temp.get(cuarto_id)
    if override is None:
        print(f"  [INFO] No hay override activo en cuarto {cuarto_id}")
        return
    override.stop()
    override.join(timeout=3.0)
    del _overrides_temp[cuarto_id]
    print(f"  [OK] Override del cuarto {cuarto_id} detenido")


def _listar_overrides():
    if not _overrides_temp and not _overrides_presencia:
        print("  (sin overrides activos)")
        return
    if _overrides_temp:
        print("  Overrides de TEMPERATURA:")
        for cid, ov in sorted(_overrides_temp.items()):
            print(
                f"    Cuarto {cid}: modo={ov.modo} target={ov.target}C "
                f"actual={ov.valor_actual}C"
            )
    if _overrides_presencia:
        print("  Overrides de PRESENCIA:")
        for cid, ov in sorted(_overrides_presencia.items()):
            print(
                f"    Cuarto {cid}: presencia={ov.presencia} "
                f"sin_movimiento={ov.segundos_sin_movimiento}s"
            )


def _detener_todos():
    for ov in _overrides_temp.values():
        ov.stop()
    for ov in _overrides_presencia.values():
        ov.stop()
    for ov in _overrides_temp.values():
        ov.join(timeout=3.0)
    for ov in _overrides_presencia.values():
        ov.join(timeout=3.0)
    _overrides_temp.clear()
    _overrides_presencia.clear()


def _iniciar_override_presencia(publisher, presencia: bool):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return

    if cuarto_id in _overrides_presencia:
        print(
            f"  [WARN] Ya hay override de presencia en cuarto {cuarto_id}, "
            "deteniendo previo"
        )
        _overrides_presencia[cuarto_id].stop()
        _overrides_presencia[cuarto_id].join(timeout=3.0)

    override = OverridePresencia(
        publisher=publisher,
        cuarto_id=cuarto_id,
        presencia=presencia,
    )
    override.start()
    _overrides_presencia[cuarto_id] = override
    estado = "ON" if presencia else "OFF"
    print(f"  [OK] Override presencia {estado} iniciado en cuarto {cuarto_id}")


def _detener_override_presencia():
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    override = _overrides_presencia.get(cuarto_id)
    if override is None:
        print(f"  [INFO] No hay override de presencia activo en cuarto {cuarto_id}")
        return
    override.stop()
    override.join(timeout=3.0)
    del _overrides_presencia[cuarto_id]
    print(f"  [OK] Override de presencia del cuarto {cuarto_id} detenido")


def _leer_potencia_pct() -> int | None:
    try:
        valor = input("  Potencia (0-100)> ").strip()
        pot = int(valor)
        if not 0 <= pot <= 100:
            print(f"  [ERROR] potencia fuera de rango: {pot}")
            return None
        return pot
    except ValueError:
        print("  [ERROR] potencia debe ser entero")
        return None


def _leer_duracion_minutos() -> int | None:
    """
    Devuelve None si el usuario deja el input vacio (usa default del contrato: 10).
    Devuelve int si especifica un valor positivo. None tambien en caso de error.
    """
    try:
        valor = input("  Duracion en minutos (vacio = 10)> ").strip()
        if valor == "":
            return None
        dur = int(valor)
        if dur <= 0:
            print(f"  [ERROR] duracion debe ser > 0")
            return None
        return dur
    except ValueError:
        print("  [ERROR] duracion debe ser entero")
        return None


def _forzar_refrigeracion(publisher):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    potencia = _leer_potencia_pct()
    if potencia is None:
        return
    duracion = _leer_duracion_minutos()
    ok = publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id,
        comando="forzar_encendido",
        potencia_pct=potencia,
        duracion_minutos=duracion,
    )
    if ok:
        dur_str = f"{duracion} min" if duracion is not None else "default 10 min"
        print(
            f"  [OK] Forzar refrigeracion cuarto {cuarto_id} "
            f"al {potencia}% por {dur_str}"
        )
    else:
        print(f"  [ERROR] No se pudo enviar el comando")


def _cancelar_refrigeracion(publisher):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    # Contrato v3.0: potencia_pct es obligatorio incluso para cancelar_forzado.
    # Usamos 0 porque el efecto de cancelar es apagar el forzado.
    ok = publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id,
        comando="cancelar_forzado",
        potencia_pct=0,
    )
    if ok:
        print(f"  [OK] Cancelar forzado de refrigeracion cuarto {cuarto_id}")
    else:
        print(f"  [ERROR] No se pudo enviar el comando")


def _ejecutar_escenario(publisher, escenario_fn):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    try:
        escenario_fn(publisher, cuarto_id)
    except KeyboardInterrupt:
        # SIGINT en un escenario cae en _cerrar globalmente; este except es por
        # si el usuario presiona Ctrl+D o el handler global se desactiva.
        print("\n  [Escenario] Interrumpido")


def _ejecutar_operacion(publisher, operacion_fn):
    """Lanza un escenario de operacion de negocio (panel/operaciones.py).
    Le pasa los dicts de overrides para que pueda registrarlos/limpiarlos
    de forma consistente con el menu principal y D6 Reset."""
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    try:
        operacion_fn(publisher, cuarto_id, _overrides_temp, _overrides_presencia)
    except KeyboardInterrupt:
        print("\n  [Operacion] Interrumpido")


def _ejecutar_reset(publisher):
    """D6 - Reset global. No pide cuarto_id (aplica a los 5)."""
    try:
        operaciones.escenario_d6_reset(
            publisher, _overrides_temp, _overrides_presencia
        )
    except KeyboardInterrupt:
        print("\n  [Reset] Interrumpido")


def _enviar_puerta_cmd(publisher, comando: str):
    cuarto_id = _leer_cuarto_id()
    if cuarto_id is None:
        return
    ok = publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando=comando)
    if ok:
        print(f"  [OK] Comando '{comando}' enviado a cuarto {cuarto_id}")
    else:
        print(f"  [ERROR] No se pudo enviar '{comando}' a cuarto {cuarto_id}")


def main():
    _imprimir_titulo()

    sesion = _prompt_sesion()
    publisher = PanelPublisher(sesion=sesion)
    sec_listener = SecurityListener()

    def _cerrar(*_):
        print("\n[Panel] Cerrando...")
        _detener_todos()
        try:
            sec_listener.desconectar()
        except Exception:
            pass
        publisher.desconectar()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cerrar)

    try:
        publisher.conectar()
        sec_listener.conectar()
    except Exception as exc:
        print(f"[Panel] [ERROR] No se pudo conectar al broker: {exc}")
        print(f"[Panel] Verifica que EMQX este corriendo en {BROKER_HOST}:{BROKER_PORT}")
        sys.exit(1)

    for _ in range(20):
        if publisher.conectado:
            break
        time.sleep(0.1)

    if not publisher.conectado:
        print("[Panel] [ERROR] Conexion no establecida. Abortando.")
        publisher.desconectar()
        sys.exit(1)

    _imprimir_sesion(publisher)

    global _modo_avanzado
    while True:
        if _modo_avanzado:
            _imprimir_menu_avanzado()
        else:
            _imprimir_menu_demo()
        opcion = _leer_opcion()

        if opcion == "0":
            _cerrar()
        elif opcion == "99":
            _modo_avanzado = not _modo_avanzado
            destino = "Avanzado" if _modo_avanzado else "Demo"
            print(f"[Panel] Modo {destino} activo.")
            continue
        elif opcion == "90":
            nueva = _prompt_sesion()
            publisher.set_sesion(nueva)
            _imprimir_sesion(publisher)
            continue

        if not _modo_avanzado:
            if opcion == "1":
                _ejecutar_operacion(publisher, operaciones.escenario_demo_operador)
            elif opcion == "2":
                _ejecutar_operacion(publisher, operaciones.escenario_demo_supervisor)
            elif opcion == "38":
                _ejecutar_reset(publisher)
            else:
                print(
                    f"[Panel] Opcion '{opcion}' no existe en modo Demo. "
                    "Usa 99 para ir al menu Avanzado."
                )
            continue

        # --- Menu Avanzado ---
        if opcion == "1":
            _iniciar_override(publisher, modo="calentamiento")
        elif opcion == "2":
            _iniciar_override(publisher, modo="enfriamiento")
        elif opcion == "3":
            _iniciar_override(publisher, modo="objetivo")
        elif opcion == "4":
            _detener_override()
        elif opcion == "5":
            _listar_overrides()
        elif opcion == "6":
            _enviar_puerta_cmd(publisher, comando="forzar_apertura")
        elif opcion == "7":
            _enviar_puerta_cmd(publisher, comando="forzar_cierre")
        elif opcion == "8":
            _enviar_puerta_cmd(publisher, comando="cancelar_cierre_auto")
        elif opcion == "9":
            _iniciar_override_presencia(publisher, presencia=True)
        elif opcion == "10":
            _iniciar_override_presencia(publisher, presencia=False)
        elif opcion == "11":
            _detener_override_presencia()
        elif opcion == "12":
            _forzar_refrigeracion(publisher)
        elif opcion == "13":
            _cancelar_refrigeracion(publisher)
        elif opcion == "14":
            _ejecutar_escenario(publisher, escenarios.escenario_a_escalada_alarma)
        elif opcion == "15":
            _ejecutar_escenario(publisher, escenarios.escenario_b_cierre_automatico)
        elif opcion == "16":
            _ejecutar_escenario(publisher, escenarios.escenario_c_cancelacion_cierre)
        elif opcion == "17":
            _ejecutar_escenario(publisher, escenarios.escenario_d_apertura_potencia)
        elif opcion == "18":
            _ejecutar_escenario(publisher, escenarios.escenario_e_forzar_refrigeracion)
        elif opcion == "19":
            _ejecutar_escenario(publisher, escenarios.escenario_f_cp_sys_01)
        elif opcion == "20":
            _ejecutar_escenario(publisher, escenarios.escenario_g_intento_operador)
        elif opcion == "30":
            _ejecutar_operacion(publisher, operaciones.escenario_d3_estado_estable)
        elif opcion == "31":
            _ejecutar_operacion(publisher, operaciones.escenario_d1_descarga)
        elif opcion == "32":
            _ejecutar_operacion(publisher, operaciones.escenario_d4_puerta_olvidada)
        elif opcion == "33":
            _ejecutar_operacion(publisher, operaciones.escenario_d7_reentrada)
        elif opcion == "34":
            _ejecutar_operacion(publisher, operaciones.escenario_d11_forzar_refrigeracion)
        elif opcion == "35":
            _ejecutar_operacion(publisher, operaciones.escenario_d12_silenciar)
        elif opcion == "36":
            _ejecutar_operacion(publisher, operaciones.escenario_d13_auditor_intenta)
        elif opcion == "37":
            _ejecutar_operacion(publisher, operaciones.escenario_d15_caida_telemetria)
        elif opcion == "38":
            _ejecutar_reset(publisher)
        else:
            print(f"[Panel] Opcion '{opcion}' no implementada todavia.")


if __name__ == "__main__":
    main()
