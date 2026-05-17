"""
SEI - Panel de control desechable
Escenarios pre-armados que orquestan los overriders y comandos
del Contrato MQTT v3.0 para reproducir los criterios de exito de
cada Sprint y el caso de prueba de sistema CP-SYS-01.

Cada escenario es una funcion bloqueante con cleanup automatico en finally.

Notas:
  - Los escenarios B, C, D y E requieren el backend Java para verificar
    end-to-end (cierre automatico, cortina, potencia 100%, registro de
    intervenciones). Sin backend, validan que el panel emite los comandos
    al broker con el formato correcto y que el simulador aplica los
    efectos locales (Puerta, CortinaDeAire, Enfriador).
  - Ctrl+C durante un escenario cierra el panel completo (los overrides
    se detienen via _detener_todos del CLI, pero los comandos colgados al
    simulador no se revierten — el usuario puede hacer cleanup manual
    desde el menu).
"""
import time

from panel.overrider import OverridePresencia, OverrideTemperatura


def _banner(titulo: str):
    print()
    print("=" * 60)
    print(f"   {titulo}")
    print("=" * 60)


def _esperar_alcance_temperatura(override: OverrideTemperatura, target: float, max_segundos: int = 120):
    """
    Espera hasta que el override alcance el target. Imprime hitos cuando
    cruza umbrales de alarma (3.0 / 4.0 C).
    """
    cruces_anunciados = set()
    transcurrido = 0
    while transcurrido < max_segundos:
        actual = override.valor_actual
        if actual >= 3.0 and "preventiva" not in cruces_anunciados:
            print(f"  >> Temperatura {actual} C — umbral PREVENTIVA cruzado")
            cruces_anunciados.add("preventiva")
        if actual >= 4.0 and "critica" not in cruces_anunciados:
            print(f"  >> Temperatura {actual} C — umbral CRITICA cruzado")
            cruces_anunciados.add("critica")
        if actual >= target - 0.05:
            print(f"  >> Temperatura objetivo alcanzada: {actual} C")
            return
        time.sleep(2)
        transcurrido += 2
    print(f"  [WARN] Tiempo agotado, temperatura actual {override.valor_actual} C")


# ────────────────────────────────────────────────────────────────────────────
# Escenario A — Escalada de alarma (HU-04, HU-05)
# ────────────────────────────────────────────────────────────────────────────

def escenario_a_escalada_alarma(publisher, cuarto_id: int):
    _banner(f"Escenario A — Escalada de alarma (HU-04, HU-05) cuarto {cuarto_id}")
    print("  Verifica en el HMI que la tarjeta del cuarto pasa por:")
    print("    gris (normal) -> ambar (preventiva 3 C) -> rojo (critica 4 C)")
    print("  Sin backend Java el HMI solo cambiara el numero de temperatura;")
    print("  el indicador de alarma depende de que el backend publique en /alarma.")
    print()

    override = OverrideTemperatura(
        publisher=publisher,
        cuarto_id=cuarto_id,
        modo="calentamiento",
        target_celsius=5.0,
    )
    override.start()
    try:
        _esperar_alcance_temperatura(override, target=5.0, max_segundos=120)
        input("  Presiona ENTER para detener el override y volver al menu...")
    finally:
        override.stop()
        override.join(timeout=3.0)
        print("  [OK] Escenario A completado")


# ────────────────────────────────────────────────────────────────────────────
# Escenario B — Cierre automatico sin presencia (HU-07)
# ────────────────────────────────────────────────────────────────────────────

def escenario_b_cierre_automatico(publisher, cuarto_id: int):
    _banner(f"Escenario B — Cierre automatico sin presencia (HU-07) cuarto {cuarto_id}")
    print("  Condiciones que se forzaran:")
    print("    - Temperatura > 4 C (CRITICA)")
    print("    - Presencia OFF (sin movimiento)")
    print("    - Puerta abierta")
    print("  Espera del backend Java: ciclo de cierre con countdown de 5 s y")
    print("  publicacion final 'cerrada' en sei/cuartos/N/puerta.")
    print()

    override_temp = OverrideTemperatura(
        publisher=publisher, cuarto_id=cuarto_id, modo="calentamiento", target_celsius=4.5
    )
    override_pres = OverridePresencia(publisher=publisher, cuarto_id=cuarto_id, presencia=False)

    override_temp.start()
    override_pres.start()
    try:
        print("  Calentando hasta 4.5 C y manteniendo ausencia...")
        _esperar_alcance_temperatura(override_temp, target=4.5, max_segundos=120)
        print("  Forzando apertura de puerta...")
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
        print("  Esperando que el backend dispare el ciclo de cierre (10 s)...")
        time.sleep(10)
        print("  >> Si el backend esta arriba, el HMI mostro countdown y la puerta")
        print("     debe estar 'cerrada' o 'cerrando' en este momento.")
        input("  Presiona ENTER para limpiar y volver al menu...")
    finally:
        override_temp.stop()
        override_pres.stop()
        override_temp.join(timeout=3.0)
        override_pres.join(timeout=3.0)
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
        print("  [OK] Escenario B completado (puerta forzada cerrada en cleanup)")


# ────────────────────────────────────────────────────────────────────────────
# Escenario C — Cancelacion de cierre por presencia (HU-07)
# ────────────────────────────────────────────────────────────────────────────

def escenario_c_cancelacion_cierre(publisher, cuarto_id: int):
    _banner(f"Escenario C — Cancelacion de cierre por presencia (HU-07) cuarto {cuarto_id}")
    print("  Repite escenario B, pero a los 3 segundos del countdown del backend")
    print("  se fuerza presencia ON. El backend debe publicar 'cierre_cancelado'.")
    print()

    override_temp = OverrideTemperatura(
        publisher=publisher, cuarto_id=cuarto_id, modo="calentamiento", target_celsius=4.5
    )
    override_pres = OverridePresencia(publisher=publisher, cuarto_id=cuarto_id, presencia=False)

    override_temp.start()
    override_pres.start()
    try:
        _esperar_alcance_temperatura(override_temp, target=4.5, max_segundos=120)
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
        print("  Esperando 3 s del countdown del backend antes de cancelar...")
        time.sleep(3)
        print("  Forzando presencia ON para cancelar el cierre...")
        # Detiene override de ausencia y arranca uno de presencia
        override_pres.stop()
        override_pres.join(timeout=3.0)
        override_pres = OverridePresencia(
            publisher=publisher, cuarto_id=cuarto_id, presencia=True
        )
        override_pres.start()
        print("  Esperando 5 s para que el backend reaccione...")
        time.sleep(5)
        print("  >> Si el backend esta arriba, el HMI debio mostrar el toast")
        print("     'Cierre automatico cancelado en Cuarto N — presencia detectada.'")
        input("  Presiona ENTER para limpiar y volver al menu...")
    finally:
        override_temp.stop()
        override_pres.stop()
        override_temp.join(timeout=3.0)
        override_pres.join(timeout=3.0)
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
        print("  [OK] Escenario C completado")


# ────────────────────────────────────────────────────────────────────────────
# Escenario D — Apertura + cortina + potencia (HU-06, HU-08)
# ────────────────────────────────────────────────────────────────────────────

def escenario_d_apertura_potencia(publisher, cuarto_id: int):
    _banner(f"Escenario D — Apertura, cortina y potencia (HU-06, HU-08) cuarto {cuarto_id}")
    print("  Forzamos apertura. Verificaciones esperadas:")
    print("    - Simulador: '[CortinaAire N] -> ENCENDIDA'")
    print("    - Backend (cuando exista): publica refrigeracion/cmd con potencia=100")
    print("      en menos de 2 s y refrigeracion/estado con motivo=PUERTA_ABIERTA.")
    print("    - HMI: badge de potencia en ambar, cortina activa.")
    print()

    print("  Forzando apertura...")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    print("  Esperando 30 s para observar el ciclo completo...")
    try:
        time.sleep(30)
        print("  Forzando cierre...")
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
        time.sleep(2)
        input("  Presiona ENTER para volver al menu...")
    finally:
        # Cleanup defensivo: asegurar puerta cerrada
        publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
        print("  [OK] Escenario D completado")


# ────────────────────────────────────────────────────────────────────────────
# Escenario E — Forzar refrigeracion (HU-10)
# ────────────────────────────────────────────────────────────────────────────

def escenario_e_forzar_refrigeracion(publisher, cuarto_id: int):
    _banner(f"Escenario E — Forzar refrigeracion (HU-10) cuarto {cuarto_id}")
    print("  Reproduce HU-10:")
    print("    1. Temperatura sube a 3.5 C (preventiva, condicion para forzar).")
    print("    2. Supervisor fuerza refrigeracion al 100%.")
    print("    3. Backend (cuando exista) registra en intervenciones_manuales y")
    print("       publica refrigeracion/estado con motivo=FORZADO_MANUAL.")
    print()

    override_temp = OverrideTemperatura(
        publisher=publisher, cuarto_id=cuarto_id, modo="calentamiento", target_celsius=3.5
    )
    override_temp.start()
    try:
        _esperar_alcance_temperatura(override_temp, target=3.5, max_segundos=90)
        print("  Forzando refrigeracion al 100% por 5 minutos...")
        publisher.publicar_refrigeracion_cmd(
            cuarto_id=cuarto_id,
            comando="forzar_encendido",
            potencia_pct=100,
            duracion_minutos=5,
        )
        print("  Esperando 30 s para observar el efecto...")
        time.sleep(30)
        print("  Cancelando el forzado manualmente...")
        publisher.publicar_refrigeracion_cmd(
            cuarto_id=cuarto_id, comando="cancelar_forzado", potencia_pct=0
        )
        input("  Presiona ENTER para limpiar y volver al menu...")
    finally:
        override_temp.stop()
        override_temp.join(timeout=3.0)
        # Cleanup defensivo: cancelar cualquier forzado activo
        publisher.publicar_refrigeracion_cmd(
            cuarto_id=cuarto_id, comando="cancelar_forzado", potencia_pct=0
        )
        print("  [OK] Escenario E completado")


# ────────────────────────────────────────────────────────────────────────────
# Escenario F — CP-SYS-01 completo (orquestacion)
# ────────────────────────────────────────────────────────────────────────────

def escenario_f_cp_sys_01(publisher, cuarto_id: int):
    _banner(f"Escenario F — CP-SYS-01 completo cuarto {cuarto_id}")
    print("  Orquesta D -> A -> B -> C -> E con pausas entre cada paso.")
    print("  Tiempo aproximado: 8-10 minutos.")
    print("  Mantén el HMI abierto (un usuario operador y otro supervisor).")
    print()
    confirm = input("  ¿Continuar? (s/N)> ").strip().lower()
    if confirm != "s":
        print("  Cancelado")
        return

    escenario_d_apertura_potencia(publisher, cuarto_id)
    print()
    print("  --- Pausa de 5 s antes del siguiente escenario ---")
    time.sleep(5)

    escenario_a_escalada_alarma(publisher, cuarto_id)
    print()
    print("  --- Pausa de 5 s ---")
    time.sleep(5)

    escenario_b_cierre_automatico(publisher, cuarto_id)
    print()
    print("  --- Pausa de 5 s ---")
    time.sleep(5)

    escenario_c_cancelacion_cierre(publisher, cuarto_id)
    print()
    print("  --- Pausa de 5 s ---")
    time.sleep(5)

    escenario_e_forzar_refrigeracion(publisher, cuarto_id)

    _banner("CP-SYS-01 completado")


# ────────────────────────────────────────────────────────────────────────────
# Escenario G — Operador intenta silenciar (CP-AUTH-02)
# ────────────────────────────────────────────────────────────────────────────

def escenario_g_intento_operador(publisher, cuarto_id: int):
    """
    Cubre CP-AUTH-02: un operador intenta silenciar una alarma critica.
    El backend debe rechazar (matriz seccion 5: silenciar requiere supervisor)
    y publicar el intento en sei/sistema/seguridad.

    Requisito previo: la sesion activa del panel debe ser rol='operador'.
    Si la sesion es supervisor, el escenario advierte y no ejecuta.
    """
    _banner(
        f"Escenario G — Operador intenta silenciar (CP-AUTH-02) cuarto {cuarto_id}"
    )

    sesion = publisher.sesion
    if sesion.rol != "operador":
        print(f"  [WARN] Sesion actual es rol='{sesion.rol}'. Para CP-AUTH-02 se")
        print("         requiere rol='operador'. Usa la opcion 90 para re-login")
        print("         como jperez antes de correr este escenario.")
        return

    print("  Pasos:")
    print("    1. Subir temperatura del cuarto a 5 C para provocar critica.")
    print("    2. Esperar a que el backend persista la alarma (alarma_id real).")
    print("    3. Publicar alarma/cmd con comando='silenciar'.")
    print("    4. Verificar que el SecurityListener recibe el rechazo.")
    print()

    override_temp = OverrideTemperatura(
        publisher=publisher, cuarto_id=cuarto_id, modo="calentamiento", target_celsius=5.0
    )
    override_temp.start()
    try:
        from panel.escenarios import _esperar_alcance_temperatura  # self-import seguro
        _esperar_alcance_temperatura(override_temp, target=5.0, max_segundos=120)
        print("  Esperando 5 s para que el backend persista la alarma critica...")
        time.sleep(5)
        print("  Publicando alarma/cmd con comando='silenciar' (operador)...")
        # alarma_id=0 si el backend no esta arriba (no se puede persistir igualmente)
        publisher.publicar_alarma_cmd(
            cuarto_id=cuarto_id, alarma_id=0, comando="silenciar"
        )
        print("  >> Si el backend esta arriba, el rechazo aparece en")
        print("     [SecListener] [SEGURIDAD] dentro de 1-2 s.")
        input("  Presiona ENTER para limpiar y volver al menu...")
    finally:
        override_temp.stop()
        override_temp.join(timeout=3.0)
        print("  [OK] Escenario G completado")
