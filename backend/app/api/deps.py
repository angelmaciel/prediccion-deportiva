"""Dependencias compartidas: sesion actual, guardas de rol y bitacora.

La autorizacion vive aca, del lado del servidor. Que el frontend esconda el
boton de admin no es una medida de seguridad: cada endpoint sensible declara
explicitamente `Depends(requerir_admin)`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.core.crypto import hash_token
from app.db.session import obtener_db
from app.modelos.auditoria import LogAcceso
from app.modelos.usuarios import Rol, Sesion, Usuario


def asegurar_utc(valor: datetime | None) -> datetime | None:
    """Normaliza a UTC. SQLite devuelve datetimes naive; Postgres, aware."""
    if valor is None:
        return None
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor


def ip_cliente(request: Request) -> str | None:
    return request.client.host if request.client else None


def registrar_acceso(
    db: Session,
    accion: str,
    request: Request,
    usuario_id: int | None = None,
    exito: bool = True,
    detalle: str | None = None,
) -> None:
    """Deja rastro de una accion sensible.

    Nunca recibe ni guarda contrasenas, tokens de sesion ni codigos TOTP: solo
    el nombre de la accion y metadatos de red.
    """
    db.add(
        LogAcceso(
            usuario_id=usuario_id,
            accion=accion,
            exito=exito,
            ip=ip_cliente(request),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            detalle=detalle[:255] if detalle else None,
        )
    )


def sesion_valida(db: Session, token: str) -> Sesion | None:
    sesion = db.execute(
        select(Sesion).where(Sesion.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if sesion is None or sesion.revocada:
        return None
    if asegurar_utc(sesion.expira_en) <= datetime.now(timezone.utc):
        return None
    return sesion


def usuario_actual_opcional(
    request: Request, db: Session = Depends(obtener_db)
) -> Usuario | None:
    token = request.cookies.get(obtener_config().cookie_nombre)
    if not token:
        return None
    sesion = sesion_valida(db, token)
    if sesion is None:
        return None
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        return None
    return usuario


def usuario_actual(
    usuario: Usuario | None = Depends(usuario_actual_opcional),
) -> Usuario:
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion no valida o expirada"
        )
    return usuario


def requerir_admin(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if usuario.rol != Rol.ADMIN:
        # Mismo mensaje generico para cualquier no-admin: no confirma que el
        # recurso exista ni que otros roles tengan acceso.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tenes permisos para esta operacion"
        )
    return usuario
