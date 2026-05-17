"""
SEI - Panel de control desechable
Autenticacion contra el backend Spring Boot (Contrato MQTT v3.0 seccion 6).

Flujo:
  1. login_real(usuario, password) -> POST /api/login con timeout corto.
  2. Si el backend responde 200, devuelve Sesion con JWT firmado.
  3. Si el backend no responde o devuelve 401, fallback a Sesion mock con
     JWT de firma invalida. El backend la rechazara cuando este arriba,
     pero el simulador Python aplica los efectos locales sin validar JWT
     (suficiente para pruebas de comportamiento aislado).

El token mock sirve unicamente para:
  - Probar el camino "sin backend" (efectos locales del simulador).
  - Cubrir CP-AUTH-02 (operador rechazado): el backend descarta el mensaje
    en el paso 2 de la matriz de la seccion 5.
"""
import json
import os
import time
import urllib.error
import urllib.request


# JWT mock con firma invalida. Header y payload base64 son validos pero la
# firma no esta computada con la clave secreta del backend, asi que el paso 2
# del Contrato v3.0 seccion 5 lo descartara.
# Header:  {"alg":"HS256","typ":"JWT"}
# Payload: {"operador_id":2,"rol":"supervisor","exp":9999999999}
_MOCK_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJvcGVyYWRvcl9pZCI6Miwicm9sIjoic3VwZXJ2aXNvciIsImV4cCI6OTk5OTk5OTk5OX0"
    ".panel_mock_signature"
)
_MOCK_OPERADOR_OPERADOR = 1
_MOCK_OPERADOR_SUPERVISOR = 2


def _default_backend_url() -> str:
    host = os.getenv("BACKEND_HOST", os.getenv("MQTT_HOST", "192.168.1.100"))
    port = os.getenv("BACKEND_PORT", "8080")
    return f"http://{host}:{port}"


BACKEND_URL = os.getenv("BACKEND_URL", _default_backend_url())
LOGIN_TIMEOUT_S = float(os.getenv("BACKEND_LOGIN_TIMEOUT_S", "3.0"))


class Sesion:
    """
    Resultado de una autenticacion. Puede ser real (jwt firmado por el
    backend) o mock (firma invalida, usada para pruebas locales).
    """

    def __init__(
        self,
        usuario: str,
        operador_id: int,
        nombre: str,
        rol: str,
        jwt_token: str,
        expira_en: int,
        es_mock: bool,
    ):
        self.usuario = usuario
        self.operador_id = operador_id
        self.nombre = nombre
        self.rol = rol
        self.jwt_token = jwt_token
        self.expira_en = expira_en
        self.es_mock = es_mock

    @property
    def expirado(self) -> bool:
        return time.time() >= self.expira_en

    def __str__(self) -> str:
        marca = " (MOCK)" if self.es_mock else ""
        return f"{self.nombre} [{self.rol}]{marca}"


def login_real(usuario: str, password: str) -> Sesion | None:
    """
    POST {BACKEND_URL}/api/login con body {usuario, password}.
    Devuelve Sesion si el backend responde 200, None si error o timeout.
    """
    url = f"{BACKEND_URL}/api/login"
    body = json.dumps({"usuario": usuario, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LOGIN_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"[Auth] [WARN] Backend respondio {exc.code}: {exc.reason}")
        return None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"[Auth] [WARN] Backend no disponible en {url}: {exc}")
        return None
    except Exception as exc:
        print(f"[Auth] [WARN] Login real fallido: {exc}")
        return None

    return Sesion(
        usuario=usuario,
        operador_id=payload["operador_id"],
        nombre=payload.get("nombre", usuario),
        rol=payload["rol"],
        jwt_token=payload["jwt_token"],
        expira_en=payload.get("expira_en", int(time.time()) + 8 * 3600),
        es_mock=False,
    )


def login_mock(usuario: str, rol: str = "supervisor") -> Sesion:
    """
    Sesion mock con JWT de firma invalida. Operador_id se asigna segun rol
    para que sea consistente con la BD esperada (1=jperez operador,
    2=alopez supervisor segun T-13-01).
    """
    operador_id = (
        _MOCK_OPERADOR_SUPERVISOR if rol == "supervisor" else _MOCK_OPERADOR_OPERADOR
    )
    return Sesion(
        usuario=usuario,
        operador_id=operador_id,
        nombre=f"{usuario} (mock)",
        rol=rol,
        jwt_token=_MOCK_JWT,
        expira_en=int(time.time()) + 8 * 3600,
        es_mock=True,
    )


def login(usuario: str, password: str, rol_fallback: str = "supervisor") -> Sesion:
    """
    Intenta login real; si el backend no responde, devuelve Sesion mock.
    El rol_fallback solo aplica al mock; en login real el rol viene del JWT.
    """
    sesion = login_real(usuario, password)
    if sesion is not None:
        print(f"[Auth] [OK] Login real exitoso: {sesion}")
        return sesion
    print(
        "[Auth] [WARN] Fallback a sesion MOCK con firma invalida. "
        "Si el backend esta arriba rechazara los comandos en sei/sistema/seguridad."
    )
    return login_mock(usuario, rol_fallback)
