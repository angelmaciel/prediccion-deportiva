"""Persistencia de los artefactos entrenados, con la base como fuente de verdad.

Por que no alcanza el disco. En produccion (Render y cualquier PaaS parecido)
el job que entrena y el servicio web que predice son procesos distintos, en
maquinas distintas, y el disco de cada uno se reinicia con el proceso. Un
`.joblib` escrito por el job de entrenamiento no existe para la API; uno escrito
por la API desaparece cuando el servicio se duerme. Lo unico que las dos partes
comparten es Postgres.

Entonces: se escribe en los dos lados y se lee en cascada. El disco queda como
cache local — evita deserializar en cada request — y la base es de donde se
rehidrata cuando ese cache no esta.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.modelo import ModeloPrediccion
from app.ml.persistencia import ARCHIVO_PUNTERO, cargar_poisson, version_activa
from app.ml.poisson import ModeloPoissonBivariado, ParametrosPoisson
from app.modelos.prediccion import VersionModelo

logger = logging.getLogger(__name__)


def _a_bytes(objeto) -> bytes:
    bufer = io.BytesIO()
    joblib.dump(objeto, bufer)
    return bufer.getvalue()


def _desde_bytes(crudo: bytes):
    return joblib.load(io.BytesIO(crudo))


def guardar_en_base(db: Session, version: str, directorio: str | Path) -> None:
    """Sube a la base los artefactos que el entrenamiento acaba de escribir."""
    fila = db.execute(
        select(VersionModelo).where(VersionModelo.version == version)
    ).scalar_one_or_none()
    if fila is None:
        logger.warning("No hay fila de version %s: los artefactos quedan solo en disco", version)
        return

    directorio = Path(directorio)
    modelo = directorio / f"modelo_{version}.joblib"
    poisson = directorio / f"poisson_{version}.joblib"
    if modelo.exists():
        fila.artefacto_modelo = modelo.read_bytes()
    if poisson.exists():
        fila.artefacto_poisson = poisson.read_bytes()


def _fila_activa(db: Session) -> VersionModelo | None:
    return db.execute(
        select(VersionModelo).where(VersionModelo.activa.is_(True))
    ).scalar_one_or_none()


def _rehidratar(directorio: Path, nombre: str, crudo: bytes) -> Path:
    """Deja el artefacto en disco para que la proxima carga no toque la base."""
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / nombre
    ruta.write_bytes(crudo)
    return ruta


def cargar_modelo(db: Session, directorio: str | Path) -> tuple[ModeloPrediccion, str] | None:
    """Modelo activo: primero el disco, y si no esta, la base.

    Devuelve `(modelo, version)`, o None si no hay ninguno entrenado todavia.
    """
    directorio = Path(directorio)
    desde_disco = ModeloPrediccion.cargar_activo(directorio)
    if desde_disco is not None and desde_disco.version:
        return desde_disco, desde_disco.version

    fila = _fila_activa(db)
    if fila is None or fila.artefacto_modelo is None:
        return None

    logger.info("Artefacto %s ausente en disco: se rehidrata desde la base", fila.version)
    _rehidratar(directorio, f"modelo_{fila.version}.joblib", fila.artefacto_modelo)
    if fila.artefacto_poisson is not None:
        _rehidratar(directorio, f"poisson_{fila.version}.joblib", fila.artefacto_poisson)
    # El puntero es lo que `cargar_activo` consulta para saber cual es el vigente.
    (directorio / ARCHIVO_PUNTERO).write_text(
        f'{{"version": "{fila.version}", "archivo": "modelo_{fila.version}.joblib"}}',
        encoding="utf-8",
    )

    modelo = ModeloPrediccion.cargar_activo(directorio)
    return (modelo, fila.version) if modelo is not None else None


def cargar_poisson_activo(db: Session, directorio: str | Path) -> ModeloPoissonBivariado | None:
    """Poisson activo, con la misma cascada disco -> base."""
    directorio = Path(directorio)
    version = version_activa(directorio)
    if version:
        desde_disco = cargar_poisson(directorio, version)
        if desde_disco is not None:
            return desde_disco

    fila = _fila_activa(db)
    if fila is None or fila.artefacto_poisson is None:
        return None

    parametros: ParametrosPoisson = _desde_bytes(fila.artefacto_poisson)
    modelo = ModeloPoissonBivariado()
    modelo.parametros = parametros
    modelo.ajustado = parametros.partidos_usados > 0
    return modelo
