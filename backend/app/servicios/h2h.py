"""Historial de enfrentamientos directos entre dos equipos.

Dos decisiones que cambian lo que se ve en pantalla:

- Solo entran partidos **anteriores** al que se esta mirando. Un H2H que
  incluyera el propio partido, o posteriores, seria informacion del futuro.
- Los promedios se calculan solo sobre los partidos que tienen el dato. Si de
  diez cruces hay estadisticas de seis, el promedio de corners divide por seis
  y se informa esa cantidad; tratar los faltantes como cero inventaria un
  equipo que no patea al arco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.modelos.futbol import EstadoPartido, Partido

# Techo de cruces a considerar: mas atras los planteles ya no se parecen en nada.
LIMITE_POR_DEFECTO = 20


@dataclass
class Acumulador:
    """Suma y cuenta por separado, porque cada estadistica puede faltar."""

    suma: float = 0.0
    n: int = 0

    def agregar(self, valor: int | float | None) -> None:
        if valor is None:
            return
        self.suma += valor
        self.n += 1

    @property
    def promedio(self) -> float | None:
        return round(self.suma / self.n, 2) if self.n else None


@dataclass
class ResumenEquipo:
    equipo_id: int
    nombre: str
    jugados: int = 0
    ganados: int = 0
    empatados: int = 0
    perdidos: int = 0
    metricas: dict[str, Acumulador] = field(default_factory=dict)

    def acumular(self, clave: str, valor: int | float | None) -> None:
        self.metricas.setdefault(clave, Acumulador()).agregar(valor)


METRICAS = (
    "goles_favor",
    "goles_contra",
    "remates",
    "remates_arco",
    "corners",
    "faltas",
    "amarillas",
    "rojas",
    "atajadas",
)


def enfrentamientos_previos(
    db: Session,
    partido: Partido,
    solo_misma_localia: bool = False,
    liga: str | None = None,
    limite: int = LIMITE_POR_DEFECTO,
) -> list[Partido]:
    """Cruces ya jugados entre los dos equipos, del mas reciente al mas viejo."""
    local_id = partido.equipo_local_id
    visitante_id = partido.equipo_visitante_id

    if solo_misma_localia:
        # Solo los partidos en los que el local de hoy tambien fue local.
        condicion = (Partido.equipo_local_id == local_id) & (
            Partido.equipo_visitante_id == visitante_id
        )
    else:
        condicion = or_(
            (Partido.equipo_local_id == local_id) & (Partido.equipo_visitante_id == visitante_id),
            (Partido.equipo_local_id == visitante_id) & (Partido.equipo_visitante_id == local_id),
        )

    consulta = (
        select(Partido)
        .options(joinedload(Partido.estadisticas))
        .where(
            condicion,
            Partido.id != partido.id,
            Partido.fecha < partido.fecha,
            Partido.estado == EstadoPartido.FINALIZADO,
            Partido.goles_local.is_not(None),
            Partido.goles_visitante.is_not(None),
        )
        .order_by(Partido.fecha.desc())
        .limit(limite)
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    return list(db.execute(consulta).unique().scalars())


def ultimos_partidos(
    db: Session,
    equipo_id: int,
    antes_de: datetime,
    localia: str | None = None,
    liga: str | None = None,
    limite: int = LIMITE_POR_DEFECTO,
) -> list[Partido]:
    """Racha reciente de un equipo contra cualquier rival.

    `localia` acota a los partidos jugados de "local" o de "visitante", que es
    lo que hace falta para comparar en igualdad de condiciones: el rendimiento
    de local y de visitante de un mismo equipo suele no parecerse en nada.
    """
    if localia == "local":
        condicion = Partido.equipo_local_id == equipo_id
    elif localia == "visitante":
        condicion = Partido.equipo_visitante_id == equipo_id
    else:
        condicion = or_(
            Partido.equipo_local_id == equipo_id,
            Partido.equipo_visitante_id == equipo_id,
        )

    consulta = (
        select(Partido)
        .options(joinedload(Partido.estadisticas))
        .where(
            condicion,
            Partido.fecha < antes_de,
            Partido.estado == EstadoPartido.FINALIZADO,
            Partido.goles_local.is_not(None),
            Partido.goles_visitante.is_not(None),
        )
        .order_by(Partido.fecha.desc())
        .limit(limite)
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    return list(db.execute(consulta).unique().scalars())


def _lado(previo: Partido, equipo_id: int) -> str:
    return "local" if previo.equipo_local_id == equipo_id else "visitante"


def _estadistica(previo: Partido, campo: str, lado: str) -> int | None:
    estadisticas = previo.estadisticas
    if estadisticas is None:
        return None
    if campo == "atajadas":
        return estadisticas.atajadas_local if lado == "local" else estadisticas.atajadas_visitante
    return getattr(estadisticas, f"{campo}_{lado}", None)


def resumir(previos: list[Partido], equipo_id: int, nombre: str) -> ResumenEquipo:
    """Agrega el rendimiento de un equipo sobre la lista de cruces."""
    resumen = ResumenEquipo(equipo_id=equipo_id, nombre=nombre)
    for previo in previos:
        lado = _lado(previo, equipo_id)
        propios = previo.goles_local if lado == "local" else previo.goles_visitante
        ajenos = previo.goles_visitante if lado == "local" else previo.goles_local

        resumen.jugados += 1
        if propios > ajenos:
            resumen.ganados += 1
        elif propios < ajenos:
            resumen.perdidos += 1
        else:
            resumen.empatados += 1

        resumen.acumular("goles_favor", propios)
        resumen.acumular("goles_contra", ajenos)
        for campo in METRICAS:
            if campo.startswith("goles_"):
                continue
            resumen.acumular(campo, _estadistica(previo, campo, lado))
    return resumen


def con_estadisticas(previos: list[Partido]) -> int:
    return sum(1 for p in previos if p.estadisticas is not None)


def desde_la_optica_de(previo: Partido, equipo_id: int) -> dict:
    """Un partido contado desde el punto de vista de uno de los dos equipos."""
    de_local = previo.equipo_local_id == equipo_id
    favor = previo.goles_local if de_local else previo.goles_visitante
    contra = previo.goles_visitante if de_local else previo.goles_local
    rival = previo.equipo_visitante if de_local else previo.equipo_local
    return {
        "partido_id": previo.id,
        "fecha": previo.fecha,
        "liga": previo.liga,
        "temporada": previo.temporada,
        "rival": rival.nombre,
        "de_local": de_local,
        "goles_favor": favor,
        "goles_contra": contra,
        "resultado": "G" if favor > contra else "P" if favor < contra else "E",
        "tiene_estadisticas": previo.estadisticas is not None,
    }
