"""Historial de aciertos del modelo — la seccion de transparencia del producto.

Se publica accuracy real por jornada (no solo un numero global), calculada
comparando cada prediccion emitida *antes* del partido contra el resultado que
efectivamente ocurrio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.modelos.futbol import EstadoPartido, Partido, Resultado
from app.modelos.prediccion import MetricaJornada, Prediccion

INDICE_CLASE = {"L": 0, "E": 1, "V": 2}

# Rango semiabierto [inicio, fin) sobre `Partido.fecha`.
Ventana = tuple[datetime, datetime]


@dataclass(slots=True)
class ResumenGlobal:
    partidos_evaluados: int
    aciertos: int
    accuracy: float
    brier: float | None
    linea_base_local: float


def _brier_de(prediccion: Prediccion, resultado: str) -> float:
    probs = (prediccion.prob_local, prediccion.prob_empate, prediccion.prob_visitante)
    objetivo = [0.0, 0.0, 0.0]
    objetivo[INDICE_CLASE[resultado]] = 1.0
    return sum((p - o) ** 2 for p, o in zip(probs, objetivo, strict=True))


def _pares_evaluables(
    db: Session, liga: str | None = None, ventana: Ventana | None = None
) -> list[tuple[Partido, Prediccion]]:
    """Partidos finalizados que tenian una prediccion previa."""
    consulta = (
        select(Partido, Prediccion)
        .join(Prediccion, Prediccion.partido_id == Partido.id)
        .where(
            Partido.estado == EstadoPartido.FINALIZADO,
            Partido.resultado_real.is_not(None),
        )
        .order_by(Partido.fecha.asc())
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    if ventana:
        inicio, fin = ventana
        consulta = consulta.where(Partido.fecha >= inicio, Partido.fecha < fin)
    return list(db.execute(consulta).unique().all())


def recalcular_metricas_por_jornada(db: Session) -> int:
    """Recalcula `metricas_jornada` desde cero. Devuelve cuantas filas escribio."""
    acumulado: dict[tuple, dict] = {}

    for partido, prediccion in _pares_evaluables(db):
        resultado = partido.resultado_real.value
        clave = (partido.liga, partido.temporada, partido.jornada, prediccion.modelo_version)
        registro = acumulado.setdefault(
            clave, {"evaluados": 0, "aciertos": 0, "brier": 0.0}
        )
        registro["evaluados"] += 1
        registro["aciertos"] += int(prediccion.resultado_predicho == resultado)
        registro["brier"] += _brier_de(prediccion, resultado)

    existentes = {
        (m.liga, m.temporada, m.jornada, m.modelo_version): m
        for m in db.execute(select(MetricaJornada)).scalars()
    }

    for clave, datos in acumulado.items():
        liga, temporada, jornada, version = clave
        metrica = existentes.get(clave)
        if metrica is None:
            metrica = MetricaJornada(
                liga=liga, temporada=temporada, jornada=jornada, modelo_version=version
            )
            db.add(metrica)
        metrica.partidos_evaluados = datos["evaluados"]
        metrica.aciertos = datos["aciertos"]
        metrica.accuracy = datos["aciertos"] / datos["evaluados"]
        metrica.brier = datos["brier"] / datos["evaluados"]

    db.commit()
    return len(acumulado)


def _acerto_en_sql():
    """Replica en SQL el `resultado_predicho` de `Prediccion`.

    Los empates de probabilidad se resuelven en el mismo orden que el
    `max(probs, key=probs.get)` de Python (L, despues E, despues V), para que
    ambos caminos den siempre el mismo numero.
    """
    predijo_local = and_(
        Prediccion.prob_local >= Prediccion.prob_empate,
        Prediccion.prob_local >= Prediccion.prob_visitante,
    )
    predijo_empate = Prediccion.prob_empate >= Prediccion.prob_visitante
    return case(
        (and_(predijo_local, Partido.resultado_real == Resultado.LOCAL), 1),
        (predijo_local, 0),
        (and_(predijo_empate, Partido.resultado_real == Resultado.EMPATE), 1),
        (predijo_empate, 0),
        (Partido.resultado_real == Resultado.VISITANTE, 1),
        else_=0,
    )


def _brier_en_sql():
    """Suma de (p - objetivo)^2 sobre las tres clases."""
    total = None
    for prob, clase in (
        (Prediccion.prob_local, Resultado.LOCAL),
        (Prediccion.prob_empate, Resultado.EMPATE),
        (Prediccion.prob_visitante, Resultado.VISITANTE),
    ):
        objetivo = case((Partido.resultado_real == clase, 1.0), else_=0.0)
        residuo = (prob - objetivo) * (prob - objetivo)
        total = residuo if total is None else total + residuo
    return total


def resumen_global(
    db: Session, liga: str | None = None, ventana: Ventana | None = None
) -> ResumenGlobal:
    """Sin `ventana` recorre todo el historico; con ella, solo ese rango de fechas.

    Se agrega en la base y no en Python: son cuatro numeros, y materializar
    cientos de miles de objetos ORM para sumarlos costaba segundos enteros en
    la vista de historico completo.
    """
    acierto = _acerto_en_sql()
    es_local = case((Partido.resultado_real == Resultado.LOCAL, 1), else_=0)

    consulta = (
        select(
            func.count(),
            func.coalesce(func.sum(acierto), 0),
            func.coalesce(func.sum(_brier_en_sql()), 0.0),
            func.coalesce(func.sum(es_local), 0),
        )
        .select_from(Partido)
        .join(Prediccion, Prediccion.partido_id == Partido.id)
        .where(
            Partido.estado == EstadoPartido.FINALIZADO,
            Partido.resultado_real.is_not(None),
        )
    )
    if liga:
        consulta = consulta.where(Partido.liga == liga)
    if ventana:
        consulta = consulta.where(Partido.fecha >= ventana[0], Partido.fecha < ventana[1])

    n, aciertos, brier_total, locales = db.execute(consulta).one()
    if not n:
        return ResumenGlobal(0, 0, 0.0, None, 0.0)

    return ResumenGlobal(
        partidos_evaluados=n,
        aciertos=aciertos,
        accuracy=aciertos / n,
        brier=brier_total / n,
        linea_base_local=locales / n,
    )


def historial_por_jornada(
    db: Session, liga: str | None = None, limite: int = 50, ventana: Ventana | None = None
) -> list[MetricaJornada]:
    consulta = select(MetricaJornada)
    if liga:
        consulta = consulta.where(MetricaJornada.liga == liga)
    if ventana:
        # `metricas_jornada` agrega por (liga, temporada, jornada) y no guarda
        # fecha, asi que hay que cruzarla contra los partidos de la ventana.
        #
        # Se hace en dos pasos a proposito. Un EXISTS correlacionado obliga al
        # motor a recorrer `partidos` una vez por fila de metricas, y ademas el
        # `IS NOT DISTINCT FROM` (necesario porque temporada y jornada son
        # nullables) no usa indice: eso medido daba mas de dos segundos. Sacar
        # primero las claves de la ventana es una sola pasada por el indice de
        # fecha y deja un puñado de tuplas para filtrar.
        claves = db.execute(
            select(Partido.liga, Partido.temporada, Partido.jornada)
            .where(Partido.fecha >= ventana[0], Partido.fecha < ventana[1])
            .distinct()
        ).all()
        if not claves:
            return []
        consulta = consulta.where(
            or_(
                *[
                    and_(
                        MetricaJornada.liga == liga_,
                        MetricaJornada.temporada.is_not_distinct_from(temporada),
                        MetricaJornada.jornada.is_not_distinct_from(jornada),
                    )
                    for liga_, temporada, jornada in claves
                ]
            )
        )
    consulta = consulta.order_by(
        MetricaJornada.liga.asc(),
        MetricaJornada.temporada.asc(),
        MetricaJornada.jornada.asc(),
    ).limit(limite)
    return list(db.execute(consulta).scalars())
