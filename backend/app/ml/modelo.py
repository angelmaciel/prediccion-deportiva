"""Modelo de clasificacion 1X2 y su serializacion.

Baseline: regresion logistica multinomial sobre features estandarizadas. Es
lineal, rapida de reentrenar cada semana y — lo mas importante para este
proyecto — devuelve probabilidades razonablemente calibradas, que es lo que
consume la seccion de transparencia. Random Forest queda disponible como
alternativa configurable para comparar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.features import NOMBRES_FEATURES

CLASES = ("L", "E", "V")
ALGORITMOS = ("logistica", "random_forest")


@dataclass(slots=True)
class ResultadoPrediccion:
    prob_local: float
    prob_empate: float
    prob_visitante: float

    def como_tupla(self) -> tuple[float, float, float]:
        return self.prob_local, self.prob_empate, self.prob_visitante


def construir_pipeline(algoritmo: str = "logistica", semilla: int = 42) -> Pipeline:
    if algoritmo == "logistica":
        # Multinomial es el comportamiento por defecto desde sklearn 1.5+.
        clasificador = LogisticRegression(
            max_iter=1000,
            C=1.0,
            class_weight="balanced",  # el empate es minoritario; sin esto casi nunca se predice
            random_state=semilla,
        )
    elif algoritmo == "random_forest":
        clasificador = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=20,
            class_weight="balanced_subsample",
            random_state=semilla,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Algoritmo no soportado: {algoritmo}. Opciones: {ALGORITMOS}")

    # El escalado es indispensable para la logistica: Elo (~1500) y dias de
    # descanso (~7) viven en escalas incomparables.
    return Pipeline([("escalador", StandardScaler()), ("clasificador", clasificador)])


class ModeloPrediccion:
    """Envuelve el pipeline de sklearn y fija el orden de clases y features."""

    def __init__(self, algoritmo: str = "logistica", semilla: int = 42) -> None:
        self.algoritmo = algoritmo
        self.semilla = semilla
        self.pipeline = construir_pipeline(algoritmo, semilla)
        self.nombres_features = list(NOMBRES_FEATURES)
        self.entrenado = False
        self.version: str | None = None

    def entrenar(self, X: np.ndarray, y: np.ndarray) -> ModeloPrediccion:
        if len(X) == 0:
            raise ValueError("No hay datos para entrenar")
        if len(set(y)) < 2:
            raise ValueError("Se necesitan al menos dos clases distintas para entrenar")
        self.pipeline.fit(X, y)
        self.entrenado = True
        return self

    def predecir_probabilidades(self, X: np.ndarray) -> np.ndarray:
        """Matriz (n, 3) con las columnas en el orden fijo L, E, V."""
        if not self.entrenado:
            raise RuntimeError("El modelo no fue entrenado")
        crudas = self.pipeline.predict_proba(X)
        clases_modelo = list(self.pipeline.named_steps["clasificador"].classes_)
        # sklearn ordena las clases alfabeticamente (E, L, V); reordenamos a L, E, V
        # para que el resto del sistema no dependa de ese detalle.
        indices = [clases_modelo.index(c) for c in CLASES]
        return crudas[:, indices]

    def predecir_una(self, vector: list[float]) -> ResultadoPrediccion:
        probs = self.predecir_probabilidades(np.array([vector], dtype=float))[0]
        return ResultadoPrediccion(float(probs[0]), float(probs[1]), float(probs[2]))

    # --- persistencia ---

    def guardar(self, directorio: str | Path, version: str) -> Path:
        directorio = Path(directorio)
        directorio.mkdir(parents=True, exist_ok=True)
        ruta = directorio / f"modelo_{version}.joblib"
        joblib.dump(
            {
                "pipeline": self.pipeline,
                "algoritmo": self.algoritmo,
                "nombres_features": self.nombres_features,
                "version": version,
                "guardado_en": datetime.now(timezone.utc).isoformat(),
            },
            ruta,
        )
        (directorio / "modelo_activo.json").write_text(
            json.dumps({"version": version, "archivo": ruta.name}), encoding="utf-8"
        )
        self.version = version
        return ruta

    @classmethod
    def cargar(cls, ruta: str | Path) -> ModeloPrediccion:
        datos = joblib.load(Path(ruta))
        modelo = cls(algoritmo=datos.get("algoritmo", "logistica"))
        modelo.pipeline = datos["pipeline"]
        modelo.nombres_features = datos.get("nombres_features", list(NOMBRES_FEATURES))
        modelo.version = datos.get("version")
        modelo.entrenado = True
        return modelo

    @classmethod
    def cargar_activo(cls, directorio: str | Path) -> ModeloPrediccion | None:
        """Carga el modelo marcado como activo; None si todavia no hay ninguno."""
        directorio = Path(directorio)
        puntero = directorio / "modelo_activo.json"
        if not puntero.exists():
            return None
        try:
            datos = json.loads(puntero.read_text(encoding="utf-8"))
            ruta = directorio / datos["archivo"]
            if not ruta.exists():
                return None
            return cls.cargar(ruta)
        except (json.JSONDecodeError, KeyError, OSError):
            return None


def nueva_version() -> str:
    """Version legible y ordenable: v20260806T1530."""
    return datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M")
