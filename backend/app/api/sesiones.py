"""Creacion de sesiones y cookie de sesion.

Vive aparte de las rutas porque hay dos caminos que terminan en lo mismo: el
formulario de `auth` y el rodeo por Google de `oauth`. Ambos tienen que emitir
exactamente la misma cookie, con los mismos atributos de seguridad.
"""

from __future__ import annotations

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.core.crypto import hash_token
from app.core.seguridad import generar_token_sesion, vencimiento_sesion
from app.modelos.usuarios import Sesion, Usuario


def crear_sesion(db: Session, usuario: Usuario, request: Request) -> str:
    """Registra la sesion y devuelve el token en claro (solo va a la cookie)."""
    token = generar_token_sesion()
    db.add(
        Sesion(
            usuario_id=usuario.id,
            token_hash=hash_token(token),  # la base nunca guarda el token en claro
            expira_en=vencimiento_sesion(),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
    )
    return token


def establecer_cookie(respuesta: Response, token: str) -> None:
    config = obtener_config()
    respuesta.set_cookie(
        key=config.cookie_nombre,
        value=token,
        max_age=config.sesion_duracion_horas * 3600,
        httponly=True,  # inaccesible desde JavaScript
        secure=config.cookie_segura,  # solo por HTTPS en produccion
        samesite="strict",  # el navegador no la manda en requests cross-site (anti-CSRF)
        path="/",
    )
