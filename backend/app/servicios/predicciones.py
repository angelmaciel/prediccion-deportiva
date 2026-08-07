"""Generacion y consulta de predicciones para partidos proximos."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.ml.features import NOMBRES_FEATURES
from app.ml.modelo import ModeloPrediccion
from app.ml.persistencia import cargar_poisson_activo
from app.modelos.futbol import EstadoPartido, FeaturesPartido, Partido
from app.modelos.prediccion import Prediccion, VersionModelo
from app.servicios.entrenamiento import cargar_partidos_historicos, construir_dataset

logger = logging.getLogger(__name__)

HORIZONTE_DIAS = 14


class ModeloNoDisponible(RuntimeError):
    """Todavia no hay un modelo entrenado con el cual predecir."""


def modelo_activo(db: Session) -> tuple[ModeloPrediccion, str]:
    config = obtener_config()
    modelo = ModeloPrediccion.cargar_activo(config.directorio_artefactos)
    if modelo is None:
        raise ModeloNoDisponible(
            "No hay modelo entrenado. Ejecutar el reentrenamiento antes de predecir."
        )
    version = modelo.version
    if version is None:
        registro = db.execute(
            select(VersionModelo).where(VersionModelo.activa.is_(True))
        ).scalar_one_or_none()
        version = registro.version if registro else "desconocida"
    return modelo, version


def vector_desde(features: FeaturesPartido) -> list[float]:
    return [float(getattr(features, nombre)) for nombre in NOMBRES_FEATURES]


def generar_predicciones(db: Session, horizonte_dias: int = HORIZONTE_DIAS) -> int:
    """Predice todos los partidos programados dentro del horizonte.

    Reutiliza la misma pasada cronologica del entrenamiento, asi que las
    features de un partido futuro se calculan exactamente igual que las de
    entrenamiento: con la informacion disponible hasta su fecha.
    """
    modelo, version = modelo_activo(db)
    poisson = cargar_poisson_activo(obtener_config().directorio_artefactos)

    partidos = cargar_partidos_historicos(db)
    construir_dataset(partidos, persistir_en=db)  # persiste features de todos los partidos
    db.flush()


    ahora = datetime.now(timezone.utc)
    limite = ahora + timedelta(days=horizonte_dias)

    proximos = (
        db.execute(
            select(Partido, FeaturesPartido)
            .join(FeaturesPartido, FeaturesPartido.partido_id == Partido.id)
            .where(
                Partido.estado == EstadoPartido.PROGRAMADO,
                Partido.fecha >= ahora,
                Partido.fecha <= limite,
            )
            .order_by(Partido.fecha.asc())
        )
        .unique()
        .all()
    )

    existentes = {
        p.partido_id
        for p in db.execute(
            select(Prediccion).where(Prediccion.modelo_version == version)
        ).scalars()
    }

    creadas = 0
    for partido, features in proximos:
        if partido.id in existentes:
            continue
        resultado = modelo.predecir_una(vector_desde(features))
        marcador_local = marcador_visitante = None
        if poisson is not None and poisson.ajustado:
            marcador_local, marcador_visitante, _ = poisson.marcador_mas_probable(
                partido.equipo_local_id, partido.equipo_visitante_id
            )
        db.add(
            Prediccion(
                partido_id=partido.id,
                prob_local=resultado.prob_local,
                prob_empate=resultado.prob_empate,
                prob_visitante=resultado.prob_visitante,
                marcador_probable_local=marcador_local,
                marcador_probable_visitante=marcador_visitante,
                modelo_version=version,
            )
        )
        creadas += 1

    db.commit()
    logger.info("Generadas %d predicciones nuevas con el modelo %s", creadas, version)
    return creadas


def backfill_historico(
    db: Session,
    algoritmo: str = "logistica",
    tamano_bloque: int = 40,
    minimo_entrenamiento: int = 150,
) -> int:
    """Backtesting visible: predice el historico como si se hubiera hecho en vivo.

    Sin esto la seccion de transparencia no tendria nada que mostrar, porque los
    partidos viejos nunca fueron predichos. La tentacion facil seria predecirlos
    con el modelo actual — pero ese modelo ya vio esos resultados durante el
    entrenamiento, asi que el accuracy resultante seria una mentira.

    Lo que se hace aca es avanzar por bloques: entrenar con todo lo anterior al
    bloque y predecir el bloque, sin volver atras nunca. Es el mismo protocolo
    de `validacion_walk_forward`, pero guardando cada prediccion para poder
    mostrarla jornada por jornada.
    """
    partidos = cargar_partidos_historicos(db)
    X, y, ids, _ = construir_dataset(partidos, persistir_en=db)
    db.flush()

    if len(X) <= minimo_entrenamiento:
        logger.info(
            "Backfill omitido: hacen falta mas de %d partidos finalizados (hay %d)",
            minimo_entrenamiento,
            len(X),
        )
        return 0

    etiqueta_version = f"backtest-{algoritmo}"
    ya_predichos = {
        p.partido_id
        for p in db.execute(
            select(Prediccion).where(Prediccion.modelo_version == etiqueta_version)
        ).scalars()
    }

    creadas = 0
    for corte in range(minimo_entrenamiento, len(X), tamano_bloque):
        fin = min(corte + tamano_bloque, len(X))
        X_ent, y_ent = X[:corte], y[:corte]
        if len(set(y_ent)) < 2:
            continue

        modelo = ModeloPrediccion(algoritmo=algoritmo).entrenar(X_ent, y_ent)
        probabilidades = modelo.predecir_probabilidades(X[corte:fin])

        for indice, probs in enumerate(probabilidades):
            partido_id = ids[corte + indice]
            if partido_id in ya_predichos:
                continue
            db.add(
                Prediccion(
                    partido_id=partido_id,
                    prob_local=float(probs[0]),
                    prob_empate=float(probs[1]),
                    prob_visitante=float(probs[2]),
                    modelo_version=etiqueta_version,
                )
            )
            creadas += 1

    db.commit()
    logger.info("Backfill walk-forward: %d predicciones historicas generadas", creadas)
    return creadas


def prediccion_de_partido(db: Session, partido_id: int) -> Prediccion | None:
    """Ultima prediccion registrada para un partido."""
    return db.execute(
        select(Prediccion)
        .where(Prediccion.partido_id == partido_id)
        .order_by(Prediccion.creado_en.desc(), Prediccion.id.desc())
        .limit(1)
    ).scalar_one_or_none()
