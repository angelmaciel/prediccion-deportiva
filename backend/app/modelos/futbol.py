"""Equipos, partidos y features derivadas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
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

from app.db.base import Base, enum_por_valor


class Fuente(StrEnum):
    FOOTBALL_DATA = "football-data"
    API_FOOTBALL = "api-football"
    # Historico descargado de football-data.co.uk (CSV publicos, sin API).
    CSV_HISTORICO = "csv-historico"


class EstadoPartido(StrEnum):
    PROGRAMADO = "programado"
    EN_JUEGO = "en_juego"
    FINALIZADO = "finalizado"
    SUSPENDIDO = "suspendido"


class Resultado(StrEnum):
    LOCAL = "L"
    EMPATE = "E"
    VISITANTE = "V"


class Equipo(Base):
    __tablename__ = "equipos"
    __table_args__ = (UniqueConstraint("fuente", "external_id", name="uq_equipo_fuente_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    nombre_corto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    liga: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    pais: Mapped[str] = mapped_column(String(80), nullable=False)
    escudo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    fuente: Mapped[Fuente] = mapped_column(enum_por_valor(Fuente, 20))
    external_id: Mapped[str] = mapped_column(String(40), nullable=False)


class Partido(Base):
    __tablename__ = "partidos"
    __table_args__ = (
        UniqueConstraint("fuente", "external_id", name="uq_partido_fuente_external"),
        Index("ix_partido_fecha_liga", "fecha", "liga"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_local_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"), index=True)
    equipo_visitante_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    liga: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    temporada: Mapped[str | None] = mapped_column(String(20), nullable=True)
    jornada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado: Mapped[EstadoPartido] = mapped_column(
        enum_por_valor(EstadoPartido, 20), default=EstadoPartido.PROGRAMADO
    )

    goles_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goles_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resultado_real: Mapped[Resultado | None] = mapped_column(
        enum_por_valor(Resultado, 2), nullable=True
    )

    fuente: Mapped[Fuente] = mapped_column(enum_por_valor(Fuente, 20))
    external_id: Mapped[str] = mapped_column(String(40), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    equipo_local: Mapped[Equipo] = relationship(foreign_keys=[equipo_local_id], lazy="joined")
    equipo_visitante: Mapped[Equipo] = relationship(
        foreign_keys=[equipo_visitante_id], lazy="joined"
    )
    features: Mapped[FeaturesPartido | None] = relationship(
        back_populates="partido", uselist=False, cascade="all, delete-orphan"
    )
    estadisticas: Mapped[EstadisticasPartido | None] = relationship(  # noqa: F821
        back_populates="partido", uselist=False, cascade="all, delete-orphan"
    )
    predicciones: Mapped[list[Prediccion]] = relationship(  # noqa: F821
        back_populates="partido", cascade="all, delete-orphan"
    )

    @property
    def finalizado(self) -> bool:
        return self.estado == EstadoPartido.FINALIZADO and self.resultado_real is not None


class EstadisticasPartido(Base):
    """Estadisticas del partido tal como las publica la fuente.

    Van aparte de `Partido` porque solo existen para lo importado de
    football-data.co.uk: las APIs del plan gratuito dan el marcador y nada mas.
    Un partido sin fila aca es un partido del que no sabemos los remates, no un
    partido con cero remates, y la diferencia importa al promediar.
    """

    __tablename__ = "estadisticas_partido"

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(
        ForeignKey("partidos.id", ondelete="CASCADE"), unique=True, index=True
    )

    remates_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remates_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remates_arco_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remates_arco_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corners_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corners_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    faltas_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    faltas_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amarillas_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amarillas_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rojas_local: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rojas_visitante: Mapped[int | None] = mapped_column(Integer, nullable=True)

    partido: Mapped[Partido] = relationship(back_populates="estadisticas")

    @property
    def atajadas_local(self) -> int | None:
        """Estimacion: los remates al arco del rival que no terminaron en gol.

        La fuente no publica atajadas. Sobreestima un poco (un remate al arco
        puede irse por poco o pegar en el palo), asi que se expone como
        estimacion y nunca como dato duro.
        """
        return _atajadas(self.remates_arco_visitante, self.partido.goles_visitante)

    @property
    def atajadas_visitante(self) -> int | None:
        return _atajadas(self.remates_arco_local, self.partido.goles_local)


def _atajadas(remates_al_arco: int | None, goles_recibidos: int | None) -> int | None:
    if remates_al_arco is None or goles_recibidos is None:
        return None
    return max(0, remates_al_arco - goles_recibidos)


class FeaturesPartido(Base):
    """Features calculadas *con informacion previa al partido*.

    Se persisten para que el entrenamiento sea reproducible y para no recalcular
    ventanas moviles en cada request.
    """

    __tablename__ = "features_partido"

    id: Mapped[int] = mapped_column(primary_key=True)
    partido_id: Mapped[int] = mapped_column(
        ForeignKey("partidos.id", ondelete="CASCADE"), unique=True, index=True
    )

    forma_reciente_local: Mapped[float] = mapped_column(Float, default=0.0)
    forma_reciente_visitante: Mapped[float] = mapped_column(Float, default=0.0)

    h2h_local_wins: Mapped[int] = mapped_column(Integer, default=0)
    h2h_draws: Mapped[int] = mapped_column(Integer, default=0)
    h2h_away_wins: Mapped[int] = mapped_column(Integer, default=0)

    dias_descanso_local: Mapped[float] = mapped_column(Float, default=7.0)
    dias_descanso_visitante: Mapped[float] = mapped_column(Float, default=7.0)

    goles_favor_local: Mapped[float] = mapped_column(Float, default=0.0)
    goles_contra_local: Mapped[float] = mapped_column(Float, default=0.0)
    goles_favor_visitante: Mapped[float] = mapped_column(Float, default=0.0)
    goles_contra_visitante: Mapped[float] = mapped_column(Float, default=0.0)

    elo_local: Mapped[float] = mapped_column(Float, default=1500.0)
    elo_visitante: Mapped[float] = mapped_column(Float, default=1500.0)

    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    partido: Mapped[Partido] = relationship(back_populates="features")


class RatingElo(Base):
    """Rating Elo vigente por equipo, actualizado partido a partido."""

    __tablename__ = "ratings_elo"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_id: Mapped[int] = mapped_column(
        ForeignKey("equipos.id", ondelete="CASCADE"), unique=True, index=True
    )
    rating: Mapped[float] = mapped_column(Float, default=1500.0, nullable=False)
    partidos_jugados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
