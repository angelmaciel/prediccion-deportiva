"""Auditoria de accesos y control de cuota de las APIs externas."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_por_valor
from app.modelos.futbol import Fuente


class LogAcceso(Base):
    """Bitacora de acciones sensibles.

    Nunca se registran contrasenas, tokens de sesion ni codigos TOTP: solo el
    tipo de accion, el usuario (si se conoce) y metadatos de red.
    """

    __tablename__ = "logs_acceso"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    accion: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    exito: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 entra en 45
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detalle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ConsumoCuota(Base):
    """Requests gastados por dia y por fuente externa.

    Permite frenar la sincronizacion antes de que la API nos bloquee y mostrar
    el consumo en el panel de admin.
    """

    __tablename__ = "consumo_cuota"
    __table_args__ = (UniqueConstraint("fuente", "dia", name="uq_cuota_fuente_dia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente: Mapped[Fuente] = mapped_column(enum_por_valor(Fuente, 20), index=True)
    dia: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errores: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ultimo_request: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EjecucionJob(Base):
    """Resultado de cada corrida del scheduler (sincronizacion/reentrenamiento)."""

    __tablename__ = "ejecuciones_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exito: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registros_afectados: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str | None] = mapped_column(String(500), nullable=True)
