"""Endpoints de transparencia del modelo.

Requisito de producto: el usuario tiene que poder ver como le fue al modelo de
verdad — accuracy por jornada, no solo un numero global — y contra que linea de
base. Todo lo que se publica aca sale de comparar predicciones emitidas antes
del partido contra el resultado real.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import obtener_db
from app.esquemas import MetricaJornadaSalida, ResumenModeloSalida, VersionModeloSalida
from app.modelos.prediccion import VersionModelo
from app.servicios.metricas import historial_por_jornada, resumen_global

router = APIRouter(prefix="/transparencia", tags=["transparencia"])


@router.get("/resumen", response_model=ResumenModeloSalida)
def resumen(
    request: Request,
    db: Session = Depends(obtener_db),
    liga: str | None = Query(default=None, max_length=80),
) -> ResumenModeloSalida:
    version = db.execute(
        select(VersionModelo).where(VersionModelo.activa.is_(True))
    ).scalar_one_or_none()
    global_ = resumen_global(db, liga)
    return ResumenModeloSalida(
        version_activa=version.version if version else None,
        algoritmo=version.algoritmo if version else None,
        entrenado_en=version.entrenado_en if version else None,
        partidos_entrenamiento=version.partidos_entrenamiento if version else 0,
        accuracy_walk_forward=version.accuracy if version else None,
        log_loss=version.log_loss if version else None,
        brier=version.brier if version else None,
        partidos_evaluados=global_.partidos_evaluados,
        aciertos=global_.aciertos,
        accuracy_real=global_.accuracy,
        linea_base_local=global_.linea_base_local,
    )


@router.get("/jornadas", response_model=list[MetricaJornadaSalida])
def jornadas(
    request: Request,
    db: Session = Depends(obtener_db),
    liga: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=50, ge=1, le=200),
) -> list[MetricaJornadaSalida]:
    return [
        MetricaJornadaSalida.model_validate(m) for m in historial_por_jornada(db, liga, limite)
    ]


@router.get("/versiones", response_model=list[VersionModeloSalida])
def versiones(
    request: Request,
    db: Session = Depends(obtener_db),
    limite: int = Query(default=20, ge=1, le=100),
) -> list[VersionModelo]:
    """Historial de entrenamientos con sus metricas de walk-forward."""
    return list(
        db.execute(
            select(VersionModelo).order_by(VersionModelo.entrenado_en.desc()).limit(limite)
        ).scalars()
    )
