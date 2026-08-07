"""Guardado y carga del modelo de Poisson junto al clasificador 1X2."""

from __future__ import annotations

import json
from pathlib import Path

import joblib

from app.ml.poisson import ModeloPoissonBivariado, ParametrosPoisson

ARCHIVO_PUNTERO = "modelo_activo.json"


def guardar_poisson(modelo: ModeloPoissonBivariado, directorio: str | Path, version: str) -> Path:
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"poisson_{version}.joblib"
    joblib.dump(modelo.parametros, ruta)
    return ruta


def cargar_poisson(directorio: str | Path, version: str) -> ModeloPoissonBivariado | None:
    ruta = Path(directorio) / f"poisson_{version}.joblib"
    if not ruta.exists():
        return None
    parametros: ParametrosPoisson = joblib.load(ruta)
    modelo = ModeloPoissonBivariado()
    modelo.parametros = parametros
    modelo.ajustado = parametros.partidos_usados > 0
    return modelo


def version_activa(directorio: str | Path) -> str | None:
    puntero = Path(directorio) / ARCHIVO_PUNTERO
    if not puntero.exists():
        return None
    try:
        return json.loads(puntero.read_text(encoding="utf-8")).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def cargar_poisson_activo(directorio: str | Path) -> ModeloPoissonBivariado | None:
    version = version_activa(directorio)
    return cargar_poisson(directorio, version) if version else None
