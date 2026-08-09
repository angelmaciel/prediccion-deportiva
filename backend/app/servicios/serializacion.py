"""Paso de modelos de la base a los esquemas que se publican.

Vive aparte de las rutas porque hay dos consumidores: la API, que responde en
vivo, y el exportador de la instantanea, que escribe el mismo JSON a un archivo
para que el CDN lo sirva sin tocar el backend. Si cada uno armara su propia
salida, terminarian divergiendo y el frontend veria dos formas distintas del
mismo partido.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.esquemas import EquipoSalida, PartidoSalida, PrediccionSalida
from app.modelos.futbol import Partido
from app.modelos.prediccion import Prediccion


def ultimas_predicciones(db: Session, ids: list[int]) -> dict[int, Prediccion]:
    """Ultima prediccion por partido, en una sola consulta.

    El descarte de las versiones viejas se hace en la base. Cada reentrenamiento
    deja una prediccion mas por partido, asi que traerlas todas para quedarse
    con una crecia sin techo: con ocho versiones eran ocho veces mas filas
    materializadas para el mismo listado.
    """
    if not ids:
        return {}
    ultimas = (
        select(func.max(Prediccion.id))
        .where(Prediccion.partido_id.in_(ids))
        .group_by(Prediccion.partido_id)
    )
    predicciones = db.execute(select(Prediccion).where(Prediccion.id.in_(ultimas))).scalars()
    return {p.partido_id: p for p in predicciones}


def a_salida(partido: Partido, prediccion: Prediccion | None) -> PartidoSalida:
    return PartidoSalida(
        id=partido.id,
        fecha=partido.fecha,
        liga=partido.liga,
        temporada=partido.temporada,
        jornada=partido.jornada,
        estado=partido.estado.value,
        equipo_local=EquipoSalida.model_validate(partido.equipo_local),
        equipo_visitante=EquipoSalida.model_validate(partido.equipo_visitante),
        goles_local=partido.goles_local,
        goles_visitante=partido.goles_visitante,
        resultado_real=partido.resultado_real.value if partido.resultado_real else None,
        prediccion=(
            PrediccionSalida(
                prob_local=prediccion.prob_local,
                prob_empate=prediccion.prob_empate,
                prob_visitante=prediccion.prob_visitante,
                marcador_probable_local=prediccion.marcador_probable_local,
                marcador_probable_visitante=prediccion.marcador_probable_visitante,
                modelo_version=prediccion.modelo_version,
                resultado_predicho=prediccion.resultado_predicho,
                confianza=prediccion.confianza,
                creado_en=prediccion.creado_en,
            )
            if prediccion
            else None
        ),
    )


def listado_con_predicciones(db: Session, partidos: list[Partido]) -> list[PartidoSalida]:
    predicciones = ultimas_predicciones(db, [p.id for p in partidos])
    return [a_salida(p, predicciones.get(p.id)) for p in partidos]
