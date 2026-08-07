"""Endpoints de administracion.

Prefijo separado (`/admin`), verificacion de rol en el router completo y rate
limit propio, mas estricto que el general. Ningun endpoint de aca depende de
que el frontend oculte un boton.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import registrar_acceso, requerir_admin
from app.core.config import obtener_config
from app.core.limites import limiter
from app.db.session import obtener_db
from app.esquemas import (
    ConsumoCuotaSalida,
    EjecucionJobSalida,
    EntrenamientoEntrada,
    LogAccesoSalida,
    MensajeSalida,
    PliegueSalida,
    ResumenEntrenamientoSalida,
)
from app.modelos.auditoria import ConsumoCuota, EjecucionJob, LogAcceso
from app.modelos.futbol import Fuente, Partido
from app.modelos.usuarios import Usuario
from app.servicios.entrenamiento import DatosInsuficientes, entrenar_modelo
from app.servicios.ingesta.sincronizacion import sincronizar_todo
from app.servicios.metricas import recalcular_metricas_por_jornada
from app.servicios.narrativa import NarrativaNoDisponible, generar, guardar
from app.servicios.predicciones import (
    ModeloNoDisponible,
    backfill_historico,
    generar_predicciones,
)

# La guarda de rol se aplica a TODO el router, no endpoint por endpoint: asi no
# se puede agregar una ruta nueva y olvidarse de protegerla.
router = APIRouter(
    prefix="/admin",
    tags=["administracion"],
    dependencies=[Depends(requerir_admin)],
)

LIMITE_ADMIN = obtener_config().limite_admin


@router.post("/sincronizar", response_model=MensajeSalida)
@limiter.limit(LIMITE_ADMIN)
def sincronizar(
    request: Request,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> MensajeSalida:
    """Dispara la sincronizacion con las APIs externas (respeta la cuota)."""
    registrar_acceso(db, "admin_sincronizar", request, usuario_id=admin.id)
    db.commit()
    total = sincronizar_todo(db)
    return MensajeSalida(mensaje=f"Sincronizacion completada: {total} partidos procesados")


@router.post("/entrenar", response_model=ResumenEntrenamientoSalida)
@limiter.limit(LIMITE_ADMIN)
def entrenar(
    request: Request,
    datos: EntrenamientoEntrada,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> ResumenEntrenamientoSalida:
    """Reentrena el modelo y lo valida walk-forward."""
    registrar_acceso(db, "admin_entrenar", request, usuario_id=admin.id, detalle=datos.algoritmo)
    db.commit()
    try:
        resumen = entrenar_modelo(db, algoritmo=datos.algoritmo)
    except DatosInsuficientes as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ResumenEntrenamientoSalida(
        version=resumen.version,
        algoritmo=resumen.algoritmo,
        partidos_entrenamiento=resumen.partidos_entrenamiento,
        accuracy=resumen.accuracy,
        log_loss=resumen.log_loss,
        brier=resumen.brier,
        linea_base=resumen.linea_base,
        pliegues=[PliegueSalida(**p) for p in resumen.detalle["pliegues"]],
    )


@router.post("/predecir", response_model=MensajeSalida)
@limiter.limit(LIMITE_ADMIN)
def predecir(
    request: Request,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> MensajeSalida:
    registrar_acceso(db, "admin_predecir", request, usuario_id=admin.id)
    db.commit()
    try:
        creadas = generar_predicciones(db)
    except ModeloNoDisponible as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MensajeSalida(mensaje=f"{creadas} predicciones generadas")


@router.post("/backtest", response_model=MensajeSalida)
@limiter.limit(LIMITE_ADMIN)
def backtest(
    request: Request,
    datos: EntrenamientoEntrada,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> MensajeSalida:
    """Rellena el historial de aciertos prediciendo el pasado walk-forward."""
    registrar_acceso(db, "admin_backtest", request, usuario_id=admin.id, detalle=datos.algoritmo)
    db.commit()
    creadas = backfill_historico(db, algoritmo=datos.algoritmo)
    jornadas = recalcular_metricas_por_jornada(db)
    return MensajeSalida(
        mensaje=f"{creadas} predicciones historicas generadas; {jornadas} jornadas recalculadas"
    )


@router.post("/recalcular-metricas", response_model=MensajeSalida)
@limiter.limit(LIMITE_ADMIN)
def recalcular_metricas(
    request: Request,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> MensajeSalida:
    filas = recalcular_metricas_por_jornada(db)
    registrar_acceso(db, "admin_recalcular_metricas", request, usuario_id=admin.id)
    db.commit()
    return MensajeSalida(mensaje=f"{filas} jornadas recalculadas")


@router.post("/narrativa/{partido_id}", response_model=MensajeSalida)
@limiter.limit(LIMITE_ADMIN)
def generar_narrativa(
    request: Request,
    partido_id: int,
    db: Session = Depends(obtener_db),
    admin: Usuario = Depends(requerir_admin),
) -> MensajeSalida:
    """Escribe el analisis narrativo de un partido.

    Es admin y no publico porque cada llamada se paga por token: dejarlo
    abierto seria dejar abierta la billetera.
    """
    partido = db.get(Partido, partido_id)
    if partido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado")

    try:
        resultado = generar(db, partido)
    except NarrativaNoDisponible as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    guardar(db, partido, resultado)
    registrar_acceso(
        db,
        "admin_narrativa",
        request,
        usuario_id=admin.id,
        detalle=(
            f"partido {partido_id}: {resultado.tokens_entrada}+{resultado.tokens_salida} tokens"
        ),
    )
    db.commit()
    return MensajeSalida(
        mensaje=(
            f"Narrativa generada con {resultado.modelo} "
            f"({resultado.tokens_entrada} tokens de entrada, "
            f"{resultado.tokens_salida} de salida, {len(resultado.fuentes)} fuentes)"
        )
    )


@router.get("/cuotas", response_model=list[ConsumoCuotaSalida])
@limiter.limit(LIMITE_ADMIN)
def cuotas(
    request: Request,
    db: Session = Depends(obtener_db),
    dias: int = Query(default=7, ge=1, le=60),
) -> list[ConsumoCuotaSalida]:
    """Consumo de cuota por fuente y dia: monitoreo para no quedar bloqueados."""
    config = obtener_config()
    limites = {
        Fuente.API_FOOTBALL: config.api_football_cuota_diaria,
        # football-data.org limita por minuto, no por dia; se informa el equivalente.
        Fuente.FOOTBALL_DATA: config.football_data_rpm * 60 * 24,
    }
    registros = list(
        db.execute(
            select(ConsumoCuota).order_by(ConsumoCuota.dia.desc()).limit(dias * len(limites))
        ).scalars()
    )
    return [
        ConsumoCuotaSalida(
            fuente=r.fuente.value,
            dia=r.dia,
            requests=r.requests,
            errores=r.errores,
            limite_diario=limites.get(r.fuente),
        )
        for r in registros
    ]


@router.get("/jobs", response_model=list[EjecucionJobSalida])
@limiter.limit(LIMITE_ADMIN)
def jobs(
    request: Request,
    db: Session = Depends(obtener_db),
    limite: int = Query(default=20, ge=1, le=100),
) -> list[EjecucionJob]:
    return list(
        db.execute(
            select(EjecucionJob).order_by(EjecucionJob.inicio.desc()).limit(limite)
        ).scalars()
    )


@router.get("/logs", response_model=list[LogAccesoSalida])
@limiter.limit(LIMITE_ADMIN)
def logs(
    request: Request,
    db: Session = Depends(obtener_db),
    accion: str | None = Query(default=None, max_length=60),
    solo_fallidos: bool = Query(default=False),
    limite: int = Query(default=50, ge=1, le=200),
) -> list[LogAcceso]:
    """Bitacora de accesos. No contiene contrasenas, tokens ni codigos TOTP."""
    consulta = select(LogAcceso).order_by(LogAcceso.timestamp.desc()).limit(limite)
    if accion:
        consulta = consulta.where(LogAcceso.accion == accion)
    if solo_fallidos:
        consulta = consulta.where(LogAcceso.exito.is_(False))
    return list(db.execute(consulta).scalars())


@router.get("/estado", response_model=dict)
@limiter.limit(LIMITE_ADMIN)
def estado(request: Request, db: Session = Depends(obtener_db)) -> dict:
    ultima_sincro = db.execute(
        select(EjecucionJob)
        .where(EjecucionJob.job == "sincronizacion")
        .order_by(EjecucionJob.inicio.desc())
        .limit(1)
    ).scalar_one_or_none()
    ultimo_entrenamiento = db.execute(
        select(EjecucionJob)
        .where(EjecucionJob.job == "reentrenamiento")
        .order_by(EjecucionJob.inicio.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "ahora": datetime.now(timezone.utc).isoformat(),
        "scheduler_activo": obtener_config().scheduler_activo,
        "ultima_sincronizacion": ultima_sincro.inicio.isoformat() if ultima_sincro else None,
        "ultimo_entrenamiento": (
            ultimo_entrenamiento.inicio.isoformat() if ultimo_entrenamiento else None
        ),
    }
