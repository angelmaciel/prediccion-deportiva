"""Jobs programados: sincronizacion de datos y reentrenamiento semanal.

El frontend nunca dispara llamadas a las APIs externas; toda la ingesta pasa
por aca. En Render se puede usar este APScheduler embebido (plan con servicio
siempre activo) o desactivarlo y llamar a los mismos servicios desde un cron
job externo.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import obtener_config
from app.db.session import FabricaSesion
from app.servicios.entrenamiento import DatosInsuficientes, entrenar_modelo
from app.servicios.ingesta.sincronizacion import sincronizar_todo
from app.servicios.metricas import recalcular_metricas_por_jornada
from app.servicios.predicciones import (
    ModeloNoDisponible,
    backfill_historico,
    generar_predicciones,
)

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def job_sincronizacion() -> None:
    """Trae resultados y calendario, y refresca predicciones y metricas."""
    db = FabricaSesion()
    try:
        total = sincronizar_todo(db)
        logger.info("Sincronizacion: %d partidos", total)
        try:
            generar_predicciones(db)
        except ModeloNoDisponible:
            logger.info("Sin modelo entrenado todavia: no se generan predicciones")
        recalcular_metricas_por_jornada(db)
    except Exception:  # noqa: BLE001 - un job no debe tumbar el proceso
        logger.exception("Fallo el job de sincronizacion")
        db.rollback()
    finally:
        db.close()


def job_reentrenamiento() -> None:
    """Reentrena semanalmente y vuelve a predecir con el modelo nuevo."""
    db = FabricaSesion()
    try:
        resumen = entrenar_modelo(db)
        logger.info(
            "Reentrenamiento %s: accuracy walk-forward %.3f", resumen.version, resumen.accuracy
        )
        generar_predicciones(db)
        # Extiende el backtest a los partidos que se fueron jugando desde la
        # ultima corrida, para que el historial publico siga creciendo.
        backfill_historico(db)
        recalcular_metricas_por_jornada(db)
    except DatosInsuficientes as exc:
        logger.warning("Reentrenamiento omitido: %s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo el job de reentrenamiento")
        db.rollback()
    finally:
        db.close()


def iniciar_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    config = obtener_config()
    if not config.scheduler_activo:
        logger.info("Scheduler desactivado por configuracion")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        job_sincronizacion,
        CronTrigger(hour=",".join(str(h) for h in config.horas_sincronizacion), minute=0),
        id="sincronizacion",
        replace_existing=True,
        max_instances=1,  # dos corridas simultaneas gastarian cuota al pedo
        coalesce=True,
    )
    _scheduler.add_job(
        job_reentrenamiento,
        CronTrigger(
            day_of_week=config.reentrenamiento_dia_semana,
            hour=config.reentrenamiento_hora,
            minute=30,
        ),
        id="reentrenamiento",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler iniciado. Sincronizacion a las %s UTC; reentrenamiento los %s a las %d:30 UTC",
        config.sincronizacion_cron_horas,
        config.reentrenamiento_dia_semana,
        config.reentrenamiento_hora,
    )
    return _scheduler


def detener_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
