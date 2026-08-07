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
    LargeBinary,
    String,
    Text,
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


class NarrativaPartido(Base):
    """Analisis narrativo de un partido, escrito por un modelo de lenguaje.

    Se persiste por dos razones. Una es de costo: cada narrativa se paga por
    token, y regenerarla en cada visita seria tirar plata. La otra es de
    auditoria: se guarda el modelo que la escribio y las fuentes que cito, para
    poder revisar de donde salio cada afirmacion sobre lesiones o bajas.
    """

    __tablename__ = "narrativas_partido"

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(
        ForeignKey("partidos.id", ondelete="CASCADE"), unique=True, index=True
    )

    texto: Mapped[str] = mapped_column(Text, nullable=False)
    modelo: Mapped[str] = mapped_column(String(60), nullable=False)
    # URLs que el modelo consulto para lo que la base no sabe (lesiones,
    # sanciones, convocatorias). Vacio = escribio solo con datos propios.
    fuentes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    partido: Mapped[Partido] = relationship()  # noqa: F821


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

    # Los artefactos entrenados viven aca, no solo en disco. En produccion el
    # job que entrena y el servicio que predice corren en maquinas distintas, y
    # el disco de cada una es efimero: un modelo guardado solo en el disco del
    # job nunca llega a la API, y uno guardado solo en el disco de la API
    # desaparece cuando el servicio se reinicia. La base es lo unico que ambos
    # comparten. Son pocos KB: una logistica de 13 features y los parametros
    # del Poisson.
    artefacto_modelo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    artefacto_poisson: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


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
