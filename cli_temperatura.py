"""
SEI - Wrapper CLI con flags para temperatura.
Cumple T-04-04 (Sprint 2) en su forma literal:

    python cli_temperatura.py --cuarto 2 --modo calentamiento --target 5
    python cli_temperatura.py --cuarto 2 --modo enfriamiento --target -18
    python cli_temperatura.py --cuarto 2 --modo objetivo --target 3.5

Publica en sei/cuartos/{n}/temperatura con QoS=0, retain=True. El override
se mantiene hasta Ctrl+C; cuando termina, el simulador retoma el control
del topico en su siguiente ciclo.

No requiere autenticacion (temperatura es un topico de datos).
"""
import argparse
import signal
import sys
import time

from panel.overrider import OverrideTemperatura
from panel.publisher import BROKER_HOST, BROKER_PORT, PanelPublisher

_MODOS = {"calentamiento", "enfriamiento", "objetivo"}


def main():
    parser = argparse.ArgumentParser(
        description="Forzar temperatura de un cuarto SEI"
    )
    parser.add_argument("--cuarto", type=int, required=True, help="cuarto_id 1-5")
    parser.add_argument(
        "--modo", choices=sorted(_MODOS), required=True
    )
    parser.add_argument(
        "--target", type=float, required=True, help="temperatura objetivo (C)"
    )
    parser.add_argument(
        "--inicial",
        type=float,
        default=-17.0,
        help="temperatura de partida (default -17.0)",
    )
    parser.add_argument(
        "--duracion",
        type=int,
        default=None,
        help="segundos (default: hasta Ctrl+C tras alcanzar el target)",
    )
    args = parser.parse_args()

    if not 1 <= args.cuarto <= 5:
        print(f"[ERROR] cuarto fuera de rango: {args.cuarto}")
        sys.exit(2)
    if not -40.0 <= args.target <= 20.0:
        print(f"[ERROR] target fuera del rango fisico: {args.target}")
        sys.exit(2)

    publisher = PanelPublisher()
    override: OverrideTemperatura | None = None

    def _cerrar(*_):
        print("\n[cli_temperatura] Cerrando...")
        try:
            if override is not None:
                override.stop()
                override.join(timeout=3.0)
        except Exception:
            pass
        publisher.desconectar()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cerrar)

    print(f"[cli_temperatura] Conectando a EMQX {BROKER_HOST}:{BROKER_PORT}...")
    publisher.conectar()
    for _ in range(20):
        if publisher.conectado:
            break
        time.sleep(0.1)
    if not publisher.conectado:
        print("[cli_temperatura] [ERROR] No se pudo conectar al broker")
        sys.exit(1)

    override = OverrideTemperatura(
        publisher=publisher,
        cuarto_id=args.cuarto,
        modo=args.modo,
        target_celsius=args.target,
        valor_inicial=args.inicial,
    )
    override.start()
    print(
        f"[cli_temperatura] Cuarto {args.cuarto} modo={args.modo} "
        f"target={args.target}C desde {args.inicial}C"
    )

    try:
        if args.duracion is None:
            print("[cli_temperatura] Manteniendo override hasta Ctrl+C")
            while True:
                time.sleep(1)
        else:
            print(f"[cli_temperatura] Manteniendo durante {args.duracion}s")
            time.sleep(args.duracion)
    finally:
        override.stop()
        override.join(timeout=3.0)
        publisher.desconectar()
        print("[cli_temperatura] OK")


if __name__ == "__main__":
    main()
