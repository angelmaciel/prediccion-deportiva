"""Historial de aciertos del modelo — la seccion de transparencia del producto.

Se publica accuracy real por jornada (no solo un numero global), calculada
comparando cada prediccion emitida *antes* del partido contra el resultado que
efectivamente ocurrio.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.futbol import EstadoPartido, Partido
from app.modelos.prediccion import MetricaJornada, Prediccion

INDICE_CLASE = {"L": 0, "E": 1, "V": 2}


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


def _pares_evaluables(db: Session, liga: str | None = None) -> list[tuple[Partido, Prediccion]]:
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


def resumen_global(db: Session, liga: str | None = None) -> ResumenGlobal:
    pares = _pares_evaluables(db, liga)
    if not pares:
        return ResumenGlobal(0, 0, 0.0, None, 0.0)

    aciertos = 0
    brier_total = 0.0
    locales = 0
    for partido, prediccion in pares:
        resultado = partido.resultado_real.value
        aciertos += int(prediccion.resultado_predicho == resultado)
        brier_total += _brier_de(prediccion, resultado)
        locales += int(resultado == "L")

    n = len(pares)
    return ResumenGlobal(
        partidos_evaluados=n,
        aciertos=aciertos,
        accuracy=aciertos / n,
        brier=brier_total / n,
        linea_base_local=locales / n,
    )


def historial_por_jornada(
    db: Session, liga: str | None = None, limite: int = 50
) -> list[MetricaJornada]:
    consulta = select(MetricaJornada)
    if liga:
        consulta = consulta.where(MetricaJornada.liga == liga)
    consulta = consulta.order_by(
        MetricaJornada.liga.asc(),
        MetricaJornada.temporada.asc(),
        MetricaJornada.jornada.asc(),
    ).limit(limite)
    return list(db.execute(consulta).scalars())
