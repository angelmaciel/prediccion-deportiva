"""Validacion walk-forward (nunca split aleatorio).

Por que: los partidos son una serie temporal. Un `train_test_split` aleatorio
entrena con partidos de mayo y evalua con partidos de marzo, es decir usa el
futuro para predecir el pasado. El accuracy que sale de ahi es ficticio.

Walk-forward replica lo que hace el sistema en produccion: se entrena con todo
lo anterior a un corte y se evalua solo con los partidos siguientes; el corte
avanza pliegue a pliegue. Es la unica forma de que el "historial de aciertos"
que se muestra al usuario signifique algo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from app.ml.modelo import CLASES, ModeloPrediccion

MINIMO_ENTRENAMIENTO = 100
MINIMO_EVALUACION = 20


@dataclass(slots=True)
class MetricasPliegue:
    pliegue: int
    n_entrenamiento: int
    n_evaluacion: int
    accuracy: float
    log_loss: float
    brier: float


@dataclass(slots=True)
class ResultadoValidacion:
    accuracy: float
    log_loss: float
    brier: float
    pliegues: list[MetricasPliegue]
    n_total_evaluado: int

    def como_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "log_loss": self.log_loss,
            "brier": self.brier,
            "n_total_evaluado": self.n_total_evaluado,
            "pliegues": [asdict(p) for p in self.pliegues],
        }


def _matriz_objetivo(y: np.ndarray) -> np.ndarray:
    """One-hot en el orden L, E, V."""
    indice = {clase: i for i, clase in enumerate(CLASES)}
    objetivo = np.zeros((len(y), len(CLASES)))
    for fila, etiqueta in enumerate(y):
        objetivo[fila, indice[etiqueta]] = 1.0
    return objetivo


def log_loss_multiclase(y_real: np.ndarray, probabilidades: np.ndarray) -> float:
    """Recompensa la calibracion: castiga fuerte estar seguro y equivocarse."""
    objetivo = _matriz_objetivo(y_real)
    seguras = np.clip(probabilidades, 1e-15, 1 - 1e-15)
    return float(-np.mean(np.sum(objetivo * np.log(seguras), axis=1)))


def brier_multiclase(y_real: np.ndarray, probabilidades: np.ndarray) -> float:
    """Error cuadratico medio sobre el vector de probabilidades (0 = perfecto)."""
    objetivo = _matriz_objetivo(y_real)
    return float(np.mean(np.sum((probabilidades - objetivo) ** 2, axis=1)))


def accuracy_simple(y_real: np.ndarray, probabilidades: np.ndarray) -> float:
    predichas = np.array([CLASES[i] for i in np.argmax(probabilidades, axis=1)])
    return float(np.mean(predichas == y_real))


def validacion_walk_forward(
    X: np.ndarray,
    y: np.ndarray,
    algoritmo: str = "logistica",
    n_pliegues: int = 5,
    minimo_entrenamiento: int = MINIMO_ENTRENAMIENTO,
) -> ResultadoValidacion:
    """Evalua el modelo respetando el orden temporal.

    `X` e `y` deben venir ordenados cronologicamente por fecha de partido.
    Cada pliegue entrena con `[0, corte)` y evalua con `[corte, corte + paso)`.
    """
    n = len(X)
    if n != len(y):
        raise ValueError("X e y deben tener la misma longitud")
    if n < minimo_entrenamiento + MINIMO_EVALUACION:
        raise ValueError(
            f"Se necesitan al menos {minimo_entrenamiento + MINIMO_EVALUACION} partidos "
            f"para validar walk-forward; hay {n}"
        )

    disponible = n - minimo_entrenamiento
    n_pliegues = max(1, min(n_pliegues, disponible // MINIMO_EVALUACION))
    paso = disponible // n_pliegues

    pliegues: list[MetricasPliegue] = []
    todas_probs: list[np.ndarray] = []
    todos_reales: list[np.ndarray] = []

    for i in range(n_pliegues):
        corte = minimo_entrenamiento + i * paso
        fin = n if i == n_pliegues - 1 else corte + paso

        X_ent, y_ent = X[:corte], y[:corte]
        X_eval, y_eval = X[corte:fin], y[corte:fin]
        if len(X_eval) == 0 or len(set(y_ent)) < 2:
            continue

        modelo = ModeloPrediccion(algoritmo=algoritmo).entrenar(X_ent, y_ent)
        probs = modelo.predecir_probabilidades(X_eval)

        pliegues.append(
            MetricasPliegue(
                pliegue=i + 1,
                n_entrenamiento=len(X_ent),
                n_evaluacion=len(X_eval),
                accuracy=accuracy_simple(y_eval, probs),
                log_loss=log_loss_multiclase(y_eval, probs),
                brier=brier_multiclase(y_eval, probs),
            )
        )
        todas_probs.append(probs)
        todos_reales.append(y_eval)

    if not pliegues:
        raise ValueError("No se pudo formar ningun pliegue valido de validacion")

    # Metricas globales sobre la union de las evaluaciones (no promedio de
    # promedios: los pliegues pueden tener tamanos distintos).
    probs_total = np.vstack(todas_probs)
    reales_total = np.concatenate(todos_reales)
    return ResultadoValidacion(
        accuracy=accuracy_simple(reales_total, probs_total),
        log_loss=log_loss_multiclase(reales_total, probs_total),
        brier=brier_multiclase(reales_total, probs_total),
        pliegues=pliegues,
        n_total_evaluado=len(reales_total),
    )


def linea_base_siempre_local(y: np.ndarray) -> float:
    """Accuracy de la heuristica trivial 'siempre gana el local'.

    Sirve de piso: un modelo que no la supera no aporta nada.
    """
    return float(np.mean(y == "L")) if len(y) else 0.0
