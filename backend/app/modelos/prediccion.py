"""Predicciones y metricas de desempeno del modelo."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Prediccion(Base):
    __tablename__ = "predicciones"
    __table_args__ = (
        UniqueConstraint("partido_id", "modelo_version", name="uq_prediccion_partido_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(
        ForeignKey("partidos.id", ondelete="CASCADE"), index=True, nullable=False
    )
    prob_local: Mapped[float] = mapped_column(Float, nullable=False)
    prob_empate: Mapped[float] = mapped_column(Float, nullable=False)
    prob_visitante: Mapped[float] = mapped_column(Float, nullable=False)

    # Marcador mas probable segun el modelo de Poisson bivariado (opcional).
    marcador_probable_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    marcador_probable_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)

    modelo_version: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    partido: Mapped[Partido] = relationship(back_populates="predicciones")  # noqa: F821

    @property
    def resultado_predicho(self) -> str:
        probs = {
            "L": self.prob_local,
            "E": self.prob_empate,
            "V": self.prob_visitante,
        }
        return max(probs, key=probs.get)

    @property
    def confianza(self) -> float:
        return max(self.prob_local, self.prob_empate, self.prob_visitante)


class VersionModelo(Base):
    """Registro de cada entrenamiento, con sus metricas de walk-forward."""

    __tablename__ = "versiones_modelo"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    algoritmo: Mapped[str] = mapped_column(String(60), nullable=False)
    entrenado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    partidos_entrenamiento: Mapped[int] = mapped_column(Integer, default=0)

    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Detalle por pliegue de la validacion walk-forward.
    metricas_detalle: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activa: Mapped[bool] = mapped_column(default=False, nullable=False)


class MetricaJornada(Base):
    """Accuracy real por jornada: alimenta la seccion de transparencia."""

    __tablename__ = "metricas_jornada"
    __table_args__ = (
        UniqueConstraint("liga", "temporada", "jornada", "modelo_version", name="uq_metrica_j"),
        Index("ix_metrica_liga_temporada", "liga", "temporada"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    liga: Mapped[str] = mapped_column(String(80), nullable=False)
    temporada: Mapped[str | None] = mapped_column(String(20), nullable=True)
    jornada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modelo_version: Mapped[str] = mapped_column(String(40), nullable=False)

    partidos_evaluados: Mapped[int] = mapped_column(Integer, default=0)
    aciertos: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)

    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
