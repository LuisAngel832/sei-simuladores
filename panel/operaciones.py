"""
SEI - Panel de control
Escenarios de OPERACION DE NEGOCIO (D1-D15).

Diferentes de los escenarios A-G de escenarios.py:
  - escenarios.py: validan HUs tecnicas (Sprint demos).
  - operaciones.py: simulan operacion real del negocio (descarga,
    carga, puerta olvidada, etc) con tiempos realistas y respetando
    dependencias fisicas (no cerrar con presencia, etc).

Cada operacion modifica los diccionarios _overrides_temp /
_overrides_presencia del CLI para que aparezcan en "Listar overrides"
y se limpien con D6 Reset o con _detener_todos al salir.
"""
import time

from panel.overrider import OverridePresencia, OverrideTemperatura


# ── Helpers de UI ──────────────────────────────────────────────────────────

def _banner(titulo: str):
    print()
    print("=" * 60)
    print(f"   {titulo}")
    print("=" * 60)


def _fase(numero: int, descripcion: str):
    print()
    print(f"  --- FASE {numero}: {descripcion} ---")


def _info(mensaje: str):
    print(f"     {mensaje}")


def _hito(mensaje: str):
    print(f"     >> {mensaje}")


# ── Helpers de overrides registrables ──────────────────────────────────────

def _replace_override_temp(
    overrides_temp,
    publisher,
    cuarto_id: int,
    modo: str,
    target: float,
    valor_inicial: float | None = None,
):
    """Reemplaza el override de temperatura del cuarto. Lo registra en el dict
    del CLI para que aparezca en 'Listar overrides' y se limpie con Reset."""
    previo = overrides_temp.get(cuarto_id)
    if previo is not None:
        previo.stop()
        previo.join(timeout=2.0)
    kwargs = {
        "publisher": publisher,
        "cuarto_id": cuarto_id,
        "modo": modo,
        "target_celsius": target,
    }
    if valor_inicial is not None:
        kwargs["valor_inicial"] = valor_inicial
    nuevo = OverrideTemperatura(**kwargs)
    nuevo.start()
    overrides_temp[cuarto_id] = nuevo
    return nuevo


def _replace_override_pres(
    overrides_pres,
    publisher,
    cuarto_id: int,
    presencia: bool,
):
    """Reemplaza el override de presencia del cuarto."""
    previo = overrides_pres.get(cuarto_id)
    if previo is not None:
        previo.stop()
        previo.join(timeout=2.0)
    nuevo = OverridePresencia(
        publisher=publisher,
        cuarto_id=cuarto_id,
        presencia=presencia,
    )
    nuevo.start()
    overrides_pres[cuarto_id] = nuevo
    return nuevo


def _stop_override_temp(overrides_temp, cuarto_id: int):
    ov = overrides_temp.pop(cuarto_id, None)
    if ov is not None:
        ov.stop()
        ov.join(timeout=2.0)


def _stop_override_pres(overrides_pres, cuarto_id: int):
    ov = overrides_pres.pop(cuarto_id, None)
    if ov is not None:
        ov.stop()
        ov.join(timeout=2.0)


# ── Helper: esperar respetando consistencia fisica ─────────────────────────

def _esperar_temp_objetivo(override_temp, target: float, max_seg: int = 60):
    """Espera hasta que el override alcance el target o se agote el tiempo.
    Imprime hitos al cruzar 3.0 y 4.0 C."""
    cruces = set()
    elapsed = 0
    while elapsed < max_seg:
        actual = override_temp.valor_actual
        if actual >= 3.0 and "preventiva" not in cruces:
            _hito(f"Temperatura {actual:.1f}C - umbral PREVENTIVA cruzado")
            cruces.add("preventiva")
        if actual >= 4.0 and "critica" not in cruces:
            _hito(f"Temperatura {actual:.1f}C - umbral CRITICA cruzado")
            cruces.add("critica")
        if (override_temp.modo == "calentamiento" and actual >= target - 0.05) or \
           (override_temp.modo == "enfriamiento" and actual <= target + 0.05) or \
           (override_temp.modo == "objetivo"):
            return True
        time.sleep(2)
        elapsed += 2
    _info(f"[WARN] tiempo agotado, temperatura actual {override_temp.valor_actual:.1f}C")
    return False


# ════════════════════════════════════════════════════════════════════════════
# D3 — Estado estable (baseline para demos)
# ════════════════════════════════════════════════════════════════════════════

def escenario_d3_estado_estable(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D3 - Estado estable Cuarto {cuarto_id}")
    _info("Setea el cuarto en reposo controlado:")
    _info("  - Temperatura objetivo -17C (override mantiene fijo)")
    _info("  - Presencia OFF (override mantiene fijo)")
    _info("  - Puerta cerrada")
    _info("  - Refrigeracion sin forzado")
    _info("Los overrides quedan ACTIVOS para evitar ruido aleatorio.")
    _info("Para liberarlos ejecuta D6 (Reset).")

    _fase(1, "Cerrar puerta y cancelar cualquier forzado")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
    publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id, comando="cancelar_forzado", potencia_pct=0
    )
    time.sleep(2)

    _fase(2, "Activar overrides de temperatura y presencia")
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="objetivo", target=-17.0, valor_inicial=-17.0,
    )
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    time.sleep(3)

    _hito(f"Cuarto {cuarto_id} estable. Overrides activos.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D1 — Descarga de producto (con variantes carga / boost)
# ════════════════════════════════════════════════════════════════════════════

def _d1_run(
    publisher, cuarto_id, overrides_temp, overrides_pres,
    titulo: str,
    target_pico: float,
    duracion_apertura_seg: int,
):
    _banner(titulo + f" - Cuarto {cuarto_id}")
    _info(f"Timeline aproximado:")
    _info(f"  Fase 1: operador entra (presencia ON)")
    _info(f"  Fase 2: apertura de puerta - cortina activa automatica")
    _info(f"  Fase 3: descarga {duracion_apertura_seg}s - temperatura sube a {target_pico}C")
    _info(f"  Fase 4: operador sale (presencia OFF)")
    _info(f"  Fase 5: cierre de puerta (CON presencia=false verificado)")
    _info(f"  Fase 6: recuperacion termica - temperatura vuelve a -17C")

    _fase(1, "Operador entra - presencia ON")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=True)
    time.sleep(3)

    _fase(2, "Apertura de puerta")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Backend publica estado=abierta, origen=manual. Cortina se activa.")
    time.sleep(2)

    _fase(3, f"Descarga {duracion_apertura_seg}s - temperatura sube")
    over_temp = _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="calentamiento", target=target_pico, valor_inicial=-17.0,
    )
    _esperar_temp_objetivo(over_temp, target_pico, max_seg=duracion_apertura_seg)

    _fase(4, "Operador sale - presencia OFF")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    _hito("Esperando 3s para que se propague el cambio de presencia...")
    time.sleep(3)

    # Verificacion de consistencia: NO cerramos si presencia sigue siendo true
    pres_ov = overrides_pres.get(cuarto_id)
    if pres_ov is None or pres_ov.presencia is True:
        _info("[ABORT] Presencia sigue ON. No se cierra la puerta - estado inconsistente.")
        _info("        Usa D6 Reset para limpiar.")
        return

    _fase(5, "Cierre de puerta (presencia confirmada OFF)")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
    _hito("Backend publica estado=cerrada, origen=manual. Cortina se apaga.")
    time.sleep(2)

    _fase(6, "Recuperacion termica - bajando a -17C")
    over_temp = _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="enfriamiento", target=-17.0, valor_inicial=target_pico,
    )
    _esperar_temp_objetivo(over_temp, -17.0, max_seg=60)

    _hito(f"Operacion completa. Cuarto {cuarto_id} de vuelta a -17C.")
    print()


def escenario_d1_descarga(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner("Tipo de operacion")
    print("  [1] Descarga normal (temperatura sube a -2C, no escala alarma)")
    print("  [2] Carga producto caliente (sube a +1C, cruza PREVENTIVA)")
    print("  [3] Boost demo (apertura corta, foco en cortina y boost de potencia)")
    print()
    try:
        opc = input("  Tipo (1/2/3)> ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        opc = "1"

    if opc == "2":
        _d1_run(
            publisher, cuarto_id, overrides_temp, overrides_pres,
            titulo="D1 (variante CARGA caliente)",
            target_pico=1.0,
            duracion_apertura_seg=40,
        )
    elif opc == "3":
        _d1_run(
            publisher, cuarto_id, overrides_temp, overrides_pres,
            titulo="D1 (variante BOOST de potencia)",
            target_pico=-15.0,
            duracion_apertura_seg=15,
        )
    else:
        _d1_run(
            publisher, cuarto_id, overrides_temp, overrides_pres,
            titulo="D1 - Descarga de producto",
            target_pico=-2.0,
            duracion_apertura_seg=30,
        )


# ════════════════════════════════════════════════════════════════════════════
# D4 — Puerta olvidada (cierre automatico)
# ════════════════════════════════════════════════════════════════════════════

def escenario_d4_puerta_olvidada(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D4 - Puerta olvidada Cuarto {cuarto_id}")
    _info("Demuestra el cierre automatico del backend (HU-07):")
    _info("  1. Puerta queda abierta sin que haya operador adentro.")
    _info("  2. Backend detecta presencia=false sostenido y publica 'cerrando'.")
    _info("  3. Tras el countdown del backend, publica 'cerrada'.")

    _fase(1, "Estado inicial: sin presencia")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="objetivo", target=-15.0, valor_inicial=-15.0,
    )
    time.sleep(3)

    _fase(2, "Apertura de puerta sin presencia")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Backend publica estado=abierta. Inicia ventana de espera por presencia.")

    _fase(3, "Esperando que el backend dispare cierre automatico (~60s)")
    _info("Observa en el HMI: la card pasa por 'abierta' -> 'cerrando' (countdown)")
    _info("-> 'cerrada' sin intervencion manual.")
    time.sleep(60)

    _hito("Si el backend esta arriba, la puerta deberia estar 'cerrada' ahora.")
    _info("Si no esta, ejecuta D6 Reset para forzar el cierre.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D7 — Reentrada cancela cierre automatico
# ════════════════════════════════════════════════════════════════════════════

def escenario_d7_reentrada(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D7 - Reentrada cancela cierre Cuarto {cuarto_id}")
    _info("Demuestra cancelacion de cierre automatico (HU-07b):")
    _info("  1. Puerta abierta sin presencia (igual que D4).")
    _info("  2. Backend inicia countdown de cierre.")
    _info("  3. A mitad del countdown, vuelve la presencia.")
    _info("  4. Backend publica 'cierre_cancelado'. Puerta queda abierta.")

    _fase(1, "Estado inicial: sin presencia, temp neutra")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="objetivo", target=-15.0, valor_inicial=-15.0,
    )
    time.sleep(3)

    _fase(2, "Apertura sin presencia")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Backend inicia ventana de espera. Esperando 25s antes de re-entrar...")
    time.sleep(25)

    _fase(3, "Operador re-entra - presencia ON")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=True)
    _hito("Backend deberia publicar 'cierre_cancelado'. Puerta queda 'abierta'.")
    time.sleep(10)

    _fase(4, "Salida + cierre manual para dejar el cuarto limpio")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    time.sleep(3)
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_cierre")
    _hito("Cuarto vuelto a estado cerrado.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D11 — Forzar refrigeracion manual
# ════════════════════════════════════════════════════════════════════════════

def escenario_d11_forzar_refrigeracion(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D11 - Forzar refrigeracion manual Cuarto {cuarto_id}")
    _info("Demuestra HU-10 (forzar potencia desde HMI):")
    _info("  1. Temperatura sube a 3.5C (alarma PREVENTIVA).")
    _info("  2. Operador fuerza refrigeracion al 100% por 5 min.")
    _info("  3. Backend publica refrigeracion/estado motivo=FORZADO_MANUAL.")

    _fase(1, "Subir temperatura a 3.5C (preventiva)")
    over = _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="calentamiento", target=3.5, valor_inicial=-15.0,
    )
    _esperar_temp_objetivo(over, 3.5, max_seg=60)

    _fase(2, "Forzar refrigeracion 100% / 5 min")
    publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id,
        comando="forzar_encendido",
        potencia_pct=100,
        duracion_minutos=5,
    )
    _hito("Verifica en HMI: badge 'FORZADO', barra naranja al 100%.")
    _info("Manteniendo el estado 30s para observar...")
    time.sleep(30)

    _fase(3, "Cancelar forzado manual")
    publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id, comando="cancelar_forzado", potencia_pct=0,
    )
    _hito("Refrigeracion volvera a su motivo automatico.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D12 — Silenciar alarma critica
# ════════════════════════════════════════════════════════════════════════════

def escenario_d12_silenciar(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D12 - Silenciar alarma critica Cuarto {cuarto_id}")
    _info("Demuestra HU-09 (silenciar alarma critica desde HMI):")
    _info("  1. Temperatura sube a 5C (alarma CRITICA).")
    _info("  2. Esperar al backend a persistir alarma con alarma_id.")
    _info("  3. Operador publica alarma/cmd silenciar.")
    _info("  4. Backend silencia y persiste silenciada_por.")

    if publisher.sesion.rol != "operador":
        _info(f"[WARN] Sesion actual es rol='{publisher.sesion.rol}'.")
        _info("       Para HU-09 se requiere rol='operador'.")
        _info("       Usa opcion 90 para re-login como jperez.")
        return

    _fase(1, "Subir temperatura a 5C (critica)")
    over = _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="calentamiento", target=5.0, valor_inicial=-15.0,
    )
    _esperar_temp_objetivo(over, 5.0, max_seg=90)

    _fase(2, "Esperar persistencia de la alarma critica en BD (~5s)")
    time.sleep(5)

    _fase(3, "Publicar alarma/cmd silenciar")
    publisher.publicar_alarma_cmd(
        cuarto_id=cuarto_id, alarma_id=0, comando="silenciar"
    )
    _hito("Verifica en HMI: badge crítica deja de parpadear.")
    _hito("Verifica en BD: alarmas.silenciada_por != null para esta alarma.")
    time.sleep(10)

    _fase(4, "Enfriar de vuelta para limpiar")
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="enfriamiento", target=-17.0, valor_inicial=5.0,
    )
    print()


# ════════════════════════════════════════════════════════════════════════════
# D13 — Auditor intenta comando (rechazo por rol)
# ════════════════════════════════════════════════════════════════════════════

def escenario_d13_auditor_intenta(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D13 - Auditor intenta comando Cuarto {cuarto_id}")
    _info("Demuestra rechazo por rol (HU-13, CP-AUTH-02):")
    _info("  1. Sesion activa debe ser rol='supervisor' (auditor).")
    _info("  2. Panel intenta publicar puerta/cmd forzar_apertura.")
    _info("  3. Backend rechaza y publica en sei/sistema/seguridad.")
    _info("  4. SecurityListener del panel imprime el rechazo.")

    if publisher.sesion.rol != "supervisor":
        _info(f"[WARN] Sesion actual es rol='{publisher.sesion.rol}'.")
        _info("       Para CP-AUTH-02 se requiere rol='supervisor'.")
        _info("       Usa opcion 90 para re-login como cruiz.")
        return

    _fase(1, "Publicar puerta/cmd forzar_apertura como supervisor")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Esperando rechazo del backend en sei/sistema/seguridad (5s)...")
    time.sleep(5)
    _hito("Si el backend esta arriba, deberia haber aparecido un")
    _hito("'[SecListener] [SEGURIDAD]' en consola. La puerta no debio cambiar.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D15 — Caida de telemetria (timeout del HMI)
# ════════════════════════════════════════════════════════════════════════════

def escenario_d15_caida_telemetria(publisher, cuarto_id, overrides_temp, overrides_pres):
    _banner(f"D15 - Caida de telemetria Cuarto {cuarto_id}")
    _info("Demuestra el indicador 'Sin senal' del HMI (timeout 45s):")
    _info("  1. Detenemos los overrides del panel para este cuarto.")
    _info("  2. El simulador main.py debe estar apagado tambien.")
    _info("  3. A los ~45s, la card del HMI se pone GRIS con badge 'Sin senal'.")
    _info("  4. Al volver a publicar, la card se reactiva.")

    _fase(1, "Detener overrides del cuarto (silenciar panel)")
    _stop_override_temp(overrides_temp, cuarto_id)
    _stop_override_pres(overrides_pres, cuarto_id)
    _hito(f"Overrides del cuarto {cuarto_id} detenidos.")

    _info("")
    _info(">>> AHORA: si tienes main.py corriendo localmente, APAGALO")
    _info("    (Ctrl+C en su terminal). Si los simuladores corren en otra")
    _info("    maquina, pidele a tu companero que apague el suyo.")
    try:
        input("    Presiona ENTER cuando hayas apagado los simuladores...")
    except (EOFError, KeyboardInterrupt):
        return

    _fase(2, "Esperando 50s para que el HMI marque 'Sin senal'")
    for i in range(50, 0, -10):
        _info(f"  ...{i}s")
        time.sleep(10)
    _hito("Si todo funciono, el cuarto deberia verse GRIS en el HMI.")

    _info("")
    _info(">>> AHORA: vuelve a arrancar main.py (o pide al companero).")
    try:
        input("    Presiona ENTER cuando este corriendo de nuevo...")
    except (EOFError, KeyboardInterrupt):
        return

    _fase(3, "Re-establecer override estable")
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="objetivo", target=-17.0, valor_inicial=-17.0,
    )
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    _hito("Cuarto reactivado. Card del HMI debe volver a color.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# D6 — Reset (limpia TODO - sin cuarto_id, aplica a los 5 cuartos)
# ════════════════════════════════════════════════════════════════════════════

def escenario_d6_reset(publisher, overrides_temp, overrides_pres):
    _banner("D6 - Reset a estado limpio (todos los cuartos)")
    _info("Limpia todos los overrides y manda comandos de cierre/cancelar")
    _info("para los 5 cuartos. La temperatura se recupera naturalmente.")

    _fase(1, "Detener overrides de los 5 cuartos")
    for n in range(1, 6):
        _stop_override_temp(overrides_temp, n)
        _stop_override_pres(overrides_pres, n)
    _hito("Overrides detenidos.")

    _fase(2, "Forzar cierre de todas las puertas")
    for n in range(1, 6):
        publisher.publicar_puerta_cmd(cuarto_id=n, comando="forzar_cierre")
        time.sleep(0.5)
    _hito("Comandos de cierre enviados.")

    _fase(3, "Cancelar forzados de refrigeracion")
    for n in range(1, 6):
        publisher.publicar_refrigeracion_cmd(
            cuarto_id=n, comando="cancelar_forzado", potencia_pct=0,
        )
        time.sleep(0.5)
    _hito("Refrigeracion devuelta a modo automatico.")

    print()
    _info("[OK] Reset completado. El simulador retomara control en su")
    _info("     proximo ciclo. La temperatura se estabilizara sola.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# DEMO OPERADOR — Escenario integrador alineado con el speech
# ════════════════════════════════════════════════════════════════════════════

def escenario_demo_operador(publisher, cuarto_id, overrides_temp, overrides_pres):
    """
    Escenario integrador para la demo de 5 min, alineado con el speech.

    Narrativa: durante la descarga la puerta queda abierta y entra calor.
    La temperatura cruza preventiva (3 C) y critica (4 C). El sistema
    detecta presencia, por lo que NO cierra automaticamente: dispara la
    alarma para que el personal desaloje. Cuando el cuarto queda vacio,
    el backend cierra la puerta automaticamente (HU-07) y el operador
    refuerza la refrigeracion (HU-10). Todo queda firmado con JWT real.
    """
    _banner(f"DEMO OPERADOR - Cuarto {cuarto_id}")
    _info("Escenario integrador alineado con el speech:")
    _info("  1) Descarga: puerta abierta + personal adentro.")
    _info("  2) Entra calor -> T cruza umbrales preventiva y critica.")
    _info("  3) Alarma de desalojo (con presencia el sistema NO cierra).")
    _info("  4) Personal sale -> backend cierra puerta automaticamente.")
    _info("  5) Operador refuerza refrigeracion al 100%.")
    _info("  6) Temperatura vuelve a objetivo. Todo auditado.")

    if publisher.sesion.rol != "operador":
        _info(f"[WARN] Sesion actual es rol='{publisher.sesion.rol}'.")
        _info("       Para esta demo se requiere rol='operador'.")
        _info("       Usa opcion 90 para re-login como jperez.")
        return

    # FASE 1 — Descarga en curso
    _fase(1, "Descarga en curso: puerta abierta + personal adentro")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=True)
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="objetivo", target=-15.0, valor_inicial=-15.0,
    )
    time.sleep(2)
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Puerta abierta. Cortina de aire activa (HU-06, HU-08).")
    time.sleep(4)

    # FASE 2 — Calor entra, escalada de alarma
    _fase(2, "Entra calor: T cruza PREVENTIVA (3 C) y CRITICA (4 C)")
    over = _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="calentamiento", target=5.0, valor_inicial=-15.0,
    )
    _esperar_temp_objetivo(over, 5.0, max_seg=90)
    _hito("Alarma CRITICA activa (HU-04, HU-05).")

    # FASE 3 — Alarma de desalojo (presencia bloquea cierre)
    _fase(3, "Alarma de desalojo - el sistema NO cierra con personal")
    _info("Mostrar en HMI: badge critica + presencia=true.")
    _info("El backend RESPETA la presencia y espera a que el cuarto se vacie.")
    time.sleep(8)

    # FASE 4 — Personal sale, backend dispara cierre automatico
    _fase(4, "Personal sale - backend dispara cierre automatico (HU-07)")
    _replace_override_pres(overrides_pres, publisher, cuarto_id, presencia=False)
    _hito("Presencia = false. Backend inicia countdown de cierre.")
    _info("Observa en HMI: 'abierta' -> 'cerrando' (countdown) -> 'cerrada'.")
    time.sleep(60)
    _hito("Puerta cerrada por el backend. Cuarto sellado.")

    # FASE 5 — Operador refuerza refrigeracion
    _fase(5, "Operador refuerza refrigeracion al 100% / 5 min (HU-10)")
    publisher.publicar_refrigeracion_cmd(
        cuarto_id=cuarto_id,
        comando="forzar_encendido",
        potencia_pct=100,
        duracion_minutos=5,
    )
    _hito("HMI: badge FORZADO + motivo FORZADO_MANUAL + barra al 100%.")
    time.sleep(8)

    # FASE 6 — Enfriamiento + auditoria
    _fase(6, "Cuarto vuelve a objetivo; toda la secuencia auditada")
    _replace_override_temp(
        overrides_temp, publisher, cuarto_id,
        modo="enfriamiento", target=-15.0, valor_inicial=5.0,
    )
    _hito(
        f"Acciones firmadas con operador_id={publisher.sesion.operador_id} "
        f"(JWT {'mock' if publisher.sesion.es_mock else 'real'})."
    )
    _info("Trazabilidad HACCP: cada comando quedo en la BD del backend.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# DEMO SUPERVISOR — Vista de auditoria solo lectura
# ════════════════════════════════════════════════════════════════════════════

def escenario_demo_supervisor(publisher, cuarto_id, overrides_temp, overrides_pres):
    """
    Demo del supervisor de calidad (auditor) alineada con el speech:
    "ingresaremos como supervisor para mostrar la vista de auditoria en
    solo lectura, sin posibilidad de ejecutar acciones".

    El HMI le oculta los botones de comando; el panel intenta uno y el
    backend lo rechaza por rol (defensa en profundidad). Cubre HU-13 /
    CP-AUTH-02.
    """
    _banner(f"DEMO SUPERVISOR - Auditor Cuarto {cuarto_id}")
    _info("Defensa en profundidad: el supervisor solo audita.")
    _info("  1) HMI oculta los botones de comando (mostrarlo al jurado).")
    _info("  2) Si el panel intentara un comando, el backend lo rechaza.")
    _info("  3) El intento queda registrado en sei/sistema/seguridad.")

    if publisher.sesion.rol != "supervisor":
        _info(f"[WARN] Sesion actual es rol='{publisher.sesion.rol}'.")
        _info("       Para esta demo se requiere rol='supervisor'.")
        _info("       Usa opcion 90 para re-login como cruiz.")
        return

    _fase(1, "Vista de auditoria en HMI (mostrar al jurado)")
    _info("En el HMI: las cards muestran temperatura, presencia, alarmas")
    _info("e historial - pero los botones de comando estan ocultos.")
    time.sleep(6)

    _fase(2, "El panel intenta un comando (no deberia poder)")
    publisher.publicar_puerta_cmd(cuarto_id=cuarto_id, comando="forzar_apertura")
    _hito("Esperando rechazo del backend en sei/sistema/seguridad (5s)...")
    time.sleep(5)
    _hito("Si el backend esta arriba, aparecio '[SecListener] [SEGURIDAD]'.")
    _hito("La puerta NO cambio de estado.")
    _info("Trazabilidad HACCP: el intento queda firmado con cruiz/supervisor.")
    print()
