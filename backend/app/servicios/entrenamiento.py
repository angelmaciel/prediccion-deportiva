"""Orquestacion del entrenamiento: base de datos -> features -> modelo -> artefacto.

Todo el pipeline se apoya en una unica pasada cronologica sobre los partidos,
que es lo que garantiza que ninguna feature vea el resultado de su propio
partido ni de partidos posteriores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.ml.features import (
    NOMBRES_FEATURES,
    CalculadoraFeatures,
    PartidoHistorico,
    resultado_de,
)
from app.ml.modelo import ModeloPrediccion, nueva_version
from app.ml.persistencia import guardar_poisson
from app.ml.poisson import ModeloPoissonBivariado
from app.ml.validacion import (
    MINIMO_ENTRENAMIENTO,
    MINIMO_EVALUACION,
    linea_base_siempre_local,
    validacion_walk_forward,
)
from app.modelos.auditoria import EjecucionJob
from app.modelos.futbol import FeaturesPartido, Partido, RatingElo
from app.modelos.prediccion import VersionModelo

logger = logging.getLogger(__name__)


class DatosInsuficientes(RuntimeError):
    """No hay suficientes partidos finalizados para entrenar con sentido."""


@dataclass(slots=True)
class ResumenEntrenamiento:
    version: str
    algoritmo: str
    partidos_entrenamiento: int
    accuracy: float
    log_loss: float
    brier: float
    linea_base: float
    detalle: dict


def cargar_partidos_historicos(db: Session) -> list[PartidoHistorico]:
    """Todos los partidos en orden cronologico estricto.

    El desempate por id evita que dos partidos con la misma fecha se ordenen de
    forma distinta entre corridas y hagan irreproducible el entrenamiento.
    """
    filas = db.execute(
        select(
            Partido.id,
            Partido.equipo_local_id,
            Partido.equipo_visitante_id,
            Partido.fecha,
            Partido.goles_local,
            Partido.goles_visitante,
        ).order_by(Partido.fecha.asc(), Partido.id.asc())
    ).all()
    return [
        PartidoHistorico(
            id=f.id,
            equipo_local_id=f.equipo_local_id,
            equipo_visitante_id=f.equipo_visitante_id,
            fecha=f.fecha,
            goles_local=f.goles_local,
            goles_visitante=f.goles_visitante,
        )
        for f in filas
    ]


def construir_dataset(
    partidos: list[PartidoHistorico], persistir_en: Session | None = None
) -> tuple[np.ndarray, np.ndarray, list[int], CalculadoraFeatures]:
    """Pasada cronologica unica: calcula features y arma la matriz de entrenamiento.

    Devuelve `(X, y, ids, calculadora)`. `X` solo contiene partidos finalizados
    (los unicos con etiqueta) y `ids` trae el id de cada fila, en el mismo orden
    cronologico; el estado interno, en cambio, avanza sobre todos los partidos.
    """
    calculadora = CalculadoraFeatures()
    filas: list[list[float]] = []
    etiquetas: list[str] = []
    ids: list[int] = []

    existentes: dict[int, FeaturesPartido] = {}
    if persistir_en is not None:
        existentes = {
            f.partido_id: f for f in persistir_en.execute(select(FeaturesPartido)).scalars()
        }

    for partido in partidos:
        features = calculadora.features_de(partido)

        if persistir_en is not None:
            registro = existentes.get(partido.id)
            if registro is None:
                registro = FeaturesPartido(partido_id=partido.id)
                persistir_en.add(registro)
                existentes[partido.id] = registro
            for nombre, valor in features.items():
                setattr(registro, nombre, valor)

        etiqueta = resultado_de(partido)
        if etiqueta is not None:
            filas.append([features[nombre] for nombre in NOMBRES_FEATURES])
            etiquetas.append(etiqueta)
            ids.append(partido.id)

        calculadora.registrar(partido)

    X = np.array(filas, dtype=float) if filas else np.empty((0, len(NOMBRES_FEATURES)))
    y = np.array(etiquetas, dtype=object)
    return X, y, ids, calculadora


def _persistir_ratings(db: Session, calculadora: CalculadoraFeatures) -> None:
    actuales = {r.equipo_id: r for r in db.execute(select(RatingElo)).scalars()}
    for equipo_id, rating in calculadora.ratings().items():
        registro = actuales.get(equipo_id)
        if registro is None:
            registro = RatingElo(equipo_id=equipo_id)
            db.add(registro)
        registro.rating = rating


def entrenar_modelo(
    db: Session, algoritmo: str = "logistica", registrar_job: bool = True
) -> ResumenEntrenamiento:
    """Entrena, valida walk-forward, guarda el artefacto y lo marca como activo."""
    config = obtener_config()
    ejecucion: EjecucionJob | None = None
    if registrar_job:
        ejecucion = EjecucionJob(job="reentrenamiento", inicio=datetime.now(timezone.utc))
        db.add(ejecucion)
        db.flush()

    try:
        partidos = cargar_partidos_historicos(db)
        X, y, _ids, calculadora = construir_dataset(partidos, persistir_en=db)

        if len(X) < config.minimo_partidos_entrenamiento:
            raise DatosInsuficientes(
                f"Se necesitan al menos {config.minimo_partidos_entrenamiento} partidos "
                f"finalizados para entrenar; hay {len(X)}"
            )

        # 1) Validacion honesta: mide como se comportaria el modelo hacia adelante.
        #    El primer pliegue arranca a mitad del historico: entrenar con las
        #    primeras 100 filas y evaluar con las 6.000 siguientes no mide el
        #    modelo que se va a usar, mide uno que nunca existio. Ademas las
        #    primeras temporadas tienen el Elo en frio (todos en 1500).
        minimo = max(MINIMO_ENTRENAMIENTO, int(len(X) * 0.5))
        minimo = min(minimo, len(X) - MINIMO_EVALUACION)
        validacion = validacion_walk_forward(X, y, algoritmo=algoritmo, minimo_entrenamiento=minimo)

        # 2) Modelo final: se reentrena con TODO el historico, que es lo que se
        #    usara para predecir partidos futuros.
        modelo = ModeloPrediccion(algoritmo=algoritmo).entrenar(X, y)
        poisson = ModeloPoissonBivariado()
        poisson.ajustar(partidos)

        version = nueva_version()
        modelo.guardar(config.directorio_artefactos, version)
        guardar_poisson(poisson, config.directorio_artefactos, version)

        _persistir_ratings(db, calculadora)

        db.query(VersionModelo).filter(VersionModelo.activa.is_(True)).update({"activa": False})
        db.add(
            VersionModelo(
                version=version,
                algoritmo=algoritmo,
                partidos_entrenamiento=len(X),
                accuracy=validacion.accuracy,
                log_loss=validacion.log_loss,
                brier=validacion.brier,
                metricas_detalle=validacion.como_dict(),
                activa=True,
            )
        )

        resumen = ResumenEntrenamiento(
            version=version,
            algoritmo=algoritmo,
            partidos_entrenamiento=len(X),
            accuracy=validacion.accuracy,
            log_loss=validacion.log_loss,
            brier=validacion.brier,
            linea_base=linea_base_siempre_local(y),
            detalle=validacion.como_dict(),
        )

        if ejecucion is not None:
            ejecucion.exito = True
            ejecucion.registros_afectados = len(X)
            ejecucion.fin = datetime.now(timezone.utc)
            ejecucion.mensaje = f"{version}: accuracy walk-forward {validacion.accuracy:.3f}"
        db.commit()
        logger.info(
            "Modelo %s entrenado con %d partidos. Accuracy walk-forward %.3f (base %.3f)",
            version,
            len(X),
            validacion.accuracy,
            resumen.linea_base,
        )
        return resumen

    except Exception as exc:
        db.rollback()
        if ejecucion is not None:
            # El rollback descarto el registro; se vuelve a crear ya cerrado en error.
            db.add(
                EjecucionJob(
                    job="reentrenamiento",
                    inicio=datetime.now(timezone.utc),
                    fin=datetime.now(timezone.utc),
                    exito=False,
                    mensaje=str(exc)[:500],
                )
            )
            db.commit()
        raise
