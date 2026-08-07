"""Rate limiting con slowapi.

Se limita toda la API, no solo el login: protege el sistema y, sobre todo, la
cuota diaria de las APIs externas (100 req/dia en API-Football).
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import obtener_config


def clave_cliente(request: Request) -> str:
    """Identifica al cliente por sesion si esta autenticado, si no por IP.

    Usar la sesion evita que varios usuarios detras de un mismo NAT compartan
    cubeta; para anonimos la IP es lo unico disponible.
    """
    config = obtener_config()
    cookie = request.cookies.get(config.cookie_nombre)
    if cookie:
        # Solo un prefijo: alcanza para diferenciar y no deja el token en memoria del limiter.
        return f"sesion:{cookie[:16]}"
    return f"ip:{get_remote_address(request)}"


def clave_login(request: Request) -> str:
    """Para el login limitamos por IP: la cookie aun no existe."""
    return f"login:{get_remote_address(request)}"


limiter = Limiter(key_func=clave_cliente, default_limits=[obtener_config().limite_general])
