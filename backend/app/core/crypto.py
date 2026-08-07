"""Cifrado a nivel de columna (AES-256-GCM) e indices ciegos.

Los datos personales identificables (email) se guardan cifrados. Para poder
buscar por email sin descifrar toda la tabla se guarda ademas un *indice
ciego*: un HMAC-SHA256 con clave del email normalizado. El HMAC es
determinista (permite `WHERE email_indice = ...`) pero no reversible, y sin la
clave un atacante con la base de datos no puede confirmar si un email dado
esta presente.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import unicodedata

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, TypeDecorator

from app.core.config import obtener_config

LONGITUD_NONCE = 12  # recomendado para GCM


def cifrar(texto: str) -> str:
    """Cifra un string con AES-256-GCM. Devuelve base64(nonce || ciphertext+tag)."""
    clave = obtener_config().clave_aes()
    nonce = os.urandom(LONGITUD_NONCE)
    cifrado = AESGCM(clave).encrypt(nonce, texto.encode("utf-8"), None)
    return base64.b64encode(nonce + cifrado).decode("ascii")


def descifrar(valor: str) -> str:
    """Inversa de `cifrar`. Lanza si el dato fue manipulado (GCM autentica)."""
    clave = obtener_config().clave_aes()
    crudo = base64.b64decode(valor)
    nonce, cifrado = crudo[:LONGITUD_NONCE], crudo[LONGITUD_NONCE:]
    return AESGCM(clave).decrypt(nonce, cifrado, None).decode("utf-8")


def normalizar_email(email: str) -> str:
    """Normaliza para que el indice ciego sea estable ante mayusculas/unicode."""
    return unicodedata.normalize("NFKC", email).strip().lower()


def indice_ciego(valor: str) -> str:
    """HMAC-SHA256 con clave, en hex. Determinista y no reversible."""
    clave = obtener_config().clave_indice_ciego.encode("utf-8")
    return hmac.new(clave, normalizar_email(valor).encode("utf-8"), hashlib.sha256).hexdigest()


def hash_token(token: str) -> str:
    """Hash de un token de sesion para guardarlo en base sin poder reconstruirlo.

    SHA-256 crudo alcanza: el token es aleatorio de 256 bits, no una contrasena
    de baja entropia, asi que no hace falta un KDF lento.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TextoCifrado(TypeDecorator):
    """Columna de texto cifrada de forma transparente con AES-256-GCM."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return cifrar(value)

    def process_result_value(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return descifrar(value)
