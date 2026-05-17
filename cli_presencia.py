"""
SEI - Wrapper CLI con flags para presencia.
Cumple T-03-01 (Sprint 1) y T-07-01 (Sprint 3) en su forma literal:

    python cli_presencia.py --cuarto 3 --estado true
    python cli_presencia.py --cuarto 3 --estado false --duracion 60

Publica en sei/cuartos/{n}/presencia con QoS=1, retain=True. Si --duracion
no se especifica, mantiene la publicacion hasta Ctrl+C (porque el simulador
seguira sobreescribiendo el retained si se detiene la republicacion).

No requiere autenticacion (presencia es un topico de datos, no de comando).
"""
import argparse
import signal
import sys
import time

from panel.overrider import OverridePresencia
from panel.publisher import BROKER_HOST, BROKER_PORT, PanelPublisher


def _parse_bool(valor: str) -> bool:
    v = valor.strip().lower()
    if v in {"true", "1", "yes", "y", "si", "on"}:
        return True
    if v in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"valor booleano invalido: {valor}")


def main():
    parser = argparse.ArgumentParser(description="Forzar presencia en un cuarto SEI")
    parser.add_argument("--cuarto", type=int, required=True, help="cuarto_id 1-5")
    parser.add_argument(
        "--estado", type=_parse_bool, required=True, help="true|false"
    )
    parser.add_argument(
        "--duracion",
        type=int,
        default=None,
        help="segundos (default: hasta Ctrl+C)",
    )
    args = parser.parse_args()

    if not 1 <= args.cuarto <= 5:
        print(f"[ERROR] cuarto fuera de rango: {args.cuarto}")
        sys.exit(2)

    publisher = PanelPublisher()

    def _cerrar(*_):
        print("\n[cli_presencia] Cerrando...")
        try:
            override.stop()
            override.join(timeout=3.0)
        except Exception:
            pass
        publisher.desconectar()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cerrar)

    print(f"[cli_presencia] Conectando a EMQX {BROKER_HOST}:{BROKER_PORT}...")
    publisher.conectar()
    for _ in range(20):
        if publisher.conectado:
            break
        time.sleep(0.1)
    if not publisher.conectado:
        print("[cli_presencia] [ERROR] No se pudo conectar al broker")
        sys.exit(1)

    override = OverridePresencia(
        publisher=publisher, cuarto_id=args.cuarto, presencia=args.estado
    )
    override.start()
    estado = "ON" if args.estado else "OFF"
    print(f"[cli_presencia] Presencia {estado} en cuarto {args.cuarto}")

    try:
        if args.duracion is None:
            print("[cli_presencia] Manteniendo publicacion hasta Ctrl+C")
            while True:
                time.sleep(1)
        else:
            print(f"[cli_presencia] Manteniendo durante {args.duracion}s")
            time.sleep(args.duracion)
    finally:
        override.stop()
        override.join(timeout=3.0)
        publisher.desconectar()
        print("[cli_presencia] OK")


if __name__ == "__main__":
    main()
