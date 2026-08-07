"""Hasheo de contrasenas, sesiones por cookie y TOTP."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import obtener_config

# Parametros por encima del minimo de OWASP (19 MiB, t=2, p=1).
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

# Hash descartable usado para gastar el mismo tiempo cuando el usuario no
# existe, y no filtrar por temporizacion que emails estan registrados.
_HASH_SENUELO = _hasher.hash("senuelo-para-igualar-tiempos-de-respuesta")

LONGITUD_MINIMA_PASSWORD = 12


def hashear_password(password: str) -> str:
    return _hasher.hash(password)


def verificar_password(password: str, hash_guardado: str | None) -> bool:
    """Verifica la contrasena en tiempo aproximadamente constante.

    Si `hash_guardado` es None (usuario inexistente) igual se hashea contra un
    senuelo para que el tiempo de respuesta no revele la existencia de la cuenta.
    """
    objetivo = hash_guardado or _HASH_SENUELO
    try:
        _hasher.verify(objetivo, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return hash_guardado is not None


def necesita_rehash(hash_guardado: str) -> bool:
    """True si el hash quedo con parametros viejos y conviene recalcularlo."""
    try:
        return _hasher.check_needs_rehash(hash_guardado)
    except InvalidHashError:
        return True


def validar_fortaleza_password(password: str) -> list[str]:
    """Devuelve la lista de reglas incumplidas (vacia si la contrasena sirve)."""
    fallas = []
    if len(password) < LONGITUD_MINIMA_PASSWORD:
        fallas.append(f"debe tener al menos {LONGITUD_MINIMA_PASSWORD} caracteres")
    if not any(c.islower() for c in password):
        fallas.append("debe incluir al menos una minuscula")
    if not any(c.isupper() for c in password):
        fallas.append("debe incluir al menos una mayuscula")
    if not any(c.isdigit() for c in password):
        fallas.append("debe incluir al menos un numero")
    return fallas


def generar_token_sesion() -> str:
    """Token de sesion opaco de 256 bits."""
    return secrets.token_urlsafe(32)


def vencimiento_sesion() -> datetime:
    config = obtener_config()
    return datetime.now(timezone.utc) + timedelta(hours=config.sesion_duracion_horas)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


# --- TOTP (2FA para cuentas admin) ---


def generar_secreto_totp() -> str:
    return pyotp.random_base32()


def uri_provisioning_totp(secreto: str, email: str) -> str:
    return pyotp.TOTP(secreto).provisioning_uri(name=email, issuer_name="Prediccion Deportiva")


def verificar_totp(secreto: str, codigo: str) -> bool:
    """Valida el codigo con una ventana de +/-1 intervalo por desfasaje de reloj."""
    if not codigo or not codigo.strip().isdigit():
        return False
    return pyotp.TOTP(secreto).verify(codigo.strip(), valid_window=1)
