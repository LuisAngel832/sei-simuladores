"""
SEI - Wrapper CLI con flags para comandos de puerta.
Cumple T-06-01 (Sprint 2) reformulado al Contrato MQTT v3.0:

    python cli_puerta.py --cuarto 3 --cmd forzar_apertura
    python cli_puerta.py --cuarto 3 --cmd forzar_cierre --razon "limpieza"
    python cli_puerta.py --cuarto 3 --cmd cancelar_cierre_auto

En v3.0 el simulador no publica en sei/cuartos/{n}/puerta (lo hace el
Backend). Este wrapper publica en sei/cuartos/{n}/puerta/cmd con
operador_id, rol y jwt_token validos. Hace login real a /api/login
con fallback a sesion mock si el backend no responde.

Credenciales por flags:
  --usuario / --password    (defaults: cruiz / preguntar interactivo)
"""
import argparse
import getpass
import sys
import time

from panel import auth
from panel.publisher import BROKER_HOST, BROKER_PORT, PanelPublisher

_COMANDOS = {"forzar_apertura", "forzar_cierre", "cancelar_cierre_auto"}


def main():
    parser = argparse.ArgumentParser(description="Comando de puerta SEI (v3.0)")
    parser.add_argument("--cuarto", type=int, required=True, help="cuarto_id 1-5")
    parser.add_argument("--cmd", choices=sorted(_COMANDOS), required=True)
    parser.add_argument("--razon", default=None, help="justificacion textual opcional")
    parser.add_argument(
        "--usuario", default="cruiz", help="usuario para POST /api/login (default cruiz)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="password (si se omite, se solicita por stdin)",
    )
    args = parser.parse_args()

    if not 1 <= args.cuarto <= 5:
        print(f"[ERROR] cuarto fuera de rango: {args.cuarto}")
        sys.exit(2)

    password = args.password
    if password is None:
        try:
            password = getpass.getpass(f"Password de {args.usuario}> ")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)

    rol_fallback = "operador" if args.usuario.lower() == "jperez" else "supervisor"
    sesion = auth.login(args.usuario, password, rol_fallback=rol_fallback)
    print(f"[cli_puerta] Sesion: {sesion}")

    publisher = PanelPublisher(sesion=sesion)
    print(f"[cli_puerta] Conectando a EMQX {BROKER_HOST}:{BROKER_PORT}...")
    publisher.conectar()
    for _ in range(20):
        if publisher.conectado:
            break
        time.sleep(0.1)
    if not publisher.conectado:
        print("[cli_puerta] [ERROR] No se pudo conectar al broker")
        sys.exit(1)

    ok = publisher.publicar_puerta_cmd(
        cuarto_id=args.cuarto, comando=args.cmd, razon=args.razon
    )
    # Pausa breve para asegurar el flush antes de desconectar
    time.sleep(0.5)
    publisher.desconectar()

    if ok:
        print(f"[cli_puerta] OK comando '{args.cmd}' enviado al cuarto {args.cuarto}")
        sys.exit(0)
    print(f"[cli_puerta] [ERROR] No se pudo publicar '{args.cmd}'")
    sys.exit(1)


if __name__ == "__main__":
    main()
