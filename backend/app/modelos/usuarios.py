"""Usuarios y sesiones."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import TextoCifrado
from app.db.base import Base, enum_por_valor


class Rol(StrEnum):
    USUARIO = "usuario"
    ADMIN = "admin"


class Proveedor(StrEnum):
    """Como se autentica la cuenta."""

    LOCAL = "local"  # email + contrasena
    GOOGLE = "google"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    # El email es dato personal: se guarda cifrado (AES-256-GCM) y se busca por
    # `email_indice`, un HMAC determinista que no permite recuperar el original.
    email: Mapped[str] = mapped_column(TextoCifrado(512), nullable=False)
    email_indice: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Nulo en cuentas creadas con Google: no hay contrasena que verificar y el
    # login por formulario tiene que rechazarlas.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rol: Mapped[Rol] = mapped_column(enum_por_valor(Rol, 20), default=Rol.USUARIO, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    proveedor: Mapped[Proveedor] = mapped_column(
        enum_por_valor(Proveedor, 20), default=Proveedor.LOCAL, nullable=False
    )
    # Identificador estable que da Google (`sub`). No es el email: el email
    # puede cambiar, el sub no.
    proveedor_sub: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )

    totp_secreto: Mapped[str | None] = mapped_column(TextoCifrado(512), nullable=True)
    totp_activo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sesiones: Mapped[list[Sesion]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )

    @property
    def es_admin(self) -> bool:
        return self.rol == Rol.ADMIN


class Sesion(Base):
    """Sesion de servidor. La cookie lleva el token; la base solo su hash."""

    __tablename__ = "sesiones"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    usuario: Mapped[Usuario] = relationship(back_populates="sesiones")
