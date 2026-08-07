"""Calculo de features previas al partido, sin fuga de informacion.

La regla que ordena todo este modulo: las features de un partido solo pueden
mirar partidos **anteriores** a su fecha. Por eso la calculadora hace una unica
pasada cronologica: para cada partido primero *lee* el estado acumulado
(features) y recien despues lo *actualiza* con el resultado. Asi es imposible
que un resultado se filtre a su propia fila, que es el error que arruina el
backtesting.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime

from app.ml.elo import ELO_INICIAL, actualizar_elo

VENTANA_FORMA = 5  # partidos considerados para forma y promedios de goles
VENTANA_H2H = 10  # enfrentamientos directos considerados
DIAS_DESCANSO_POR_DEFECTO = 7.0
DIAS_DESCANSO_MAXIMO = 30.0  # techo: mas alla de un mes el dato no aporta

# Orden fijo de las columnas: el modelo entrenado depende de el.
NOMBRES_FEATURES: tuple[str, ...] = (
    "forma_reciente_local",
    "forma_reciente_visitante",
    "h2h_local_wins",
    "h2h_draws",
    "h2h_away_wins",
    "dias_descanso_local",
    "dias_descanso_visitante",
    "goles_favor_local",
    "goles_contra_local",
    "goles_favor_visitante",
    "goles_contra_visitante",
    "elo_local",
    "elo_visitante",
)


@dataclass(slots=True)
class PartidoHistorico:
    """Vista minima de un partido para el calculo de features."""

    id: int
    equipo_local_id: int
    equipo_visitante_id: int
    fecha: datetime
    goles_local: int | None = None
    goles_visitante: int | None = None

    @property
    def finalizado(self) -> bool:
        return self.goles_local is not None and self.goles_visitante is not None


@dataclass(slots=True)
class _RegistroEquipo:
    puntos: int
    goles_favor: int
    goles_contra: int


def puntos_de(goles_favor: int, goles_contra: int) -> int:
    if goles_favor > goles_contra:
        return 3
    if goles_favor == goles_contra:
        return 1
    return 0


class CalculadoraFeatures:
    """Mantiene el estado acumulado y produce las features de cada partido.

    Uso previsto (una sola pasada, en orden cronologico estricto)::

        calc = CalculadoraFeatures()
        for partido in partidos_ordenados_por_fecha:
            features = calc.features_de(partido)   # solo ve el pasado
            calc.registrar(partido)                # recien ahora entra al pasado
    """

    def __init__(self, elo_inicial: float = ELO_INICIAL) -> None:
        self.elo_inicial = elo_inicial
        self._elo: dict[int, float] = defaultdict(lambda: elo_inicial)
        self._historial: dict[int, deque[_RegistroEquipo]] = defaultdict(
            lambda: deque(maxlen=VENTANA_FORMA)
        )
        self._ultimo_partido: dict[int, datetime] = {}
        # clave normalizada (menor_id, mayor_id) -> resultados desde la optica del menor_id
        self._h2h: dict[tuple[int, int], deque[str]] = defaultdict(
            lambda: deque(maxlen=VENTANA_H2H)
        )
        self._partidos_registrados = 0

    # --- lectura ---

    def elo(self, equipo_id: int) -> float:
        return self._elo[equipo_id]

    def features_de(self, partido: PartidoHistorico) -> dict[str, float]:
        local, visitante = partido.equipo_local_id, partido.equipo_visitante_id
        h2h_local, h2h_empates, h2h_visitante = self._h2h_desde(local, visitante)
        return {
            "forma_reciente_local": self._forma(local),
            "forma_reciente_visitante": self._forma(visitante),
            "h2h_local_wins": float(h2h_local),
            "h2h_draws": float(h2h_empates),
            "h2h_away_wins": float(h2h_visitante),
            "dias_descanso_local": self._dias_descanso(local, partido.fecha),
            "dias_descanso_visitante": self._dias_descanso(visitante, partido.fecha),
            "goles_favor_local": self._promedio(local, "goles_favor"),
            "goles_contra_local": self._promedio(local, "goles_contra"),
            "goles_favor_visitante": self._promedio(visitante, "goles_favor"),
            "goles_contra_visitante": self._promedio(visitante, "goles_contra"),
            "elo_local": self._elo[local],
            "elo_visitante": self._elo[visitante],
        }

    def vector_de(self, partido: PartidoHistorico) -> list[float]:
        """Features en el orden fijo que espera el modelo."""
        features = self.features_de(partido)
        return [features[nombre] for nombre in NOMBRES_FEATURES]

    # --- actualizacion ---

    def registrar(self, partido: PartidoHistorico) -> None:
        """Incorpora un partido al estado. Los no finalizados solo marcan fecha."""
        local, visitante = partido.equipo_local_id, partido.equipo_visitante_id
        if not partido.finalizado:
            return

        gl, gv = partido.goles_local, partido.goles_visitante
        self._historial[local].append(
            _RegistroEquipo(puntos_de(gl, gv), goles_favor=gl, goles_contra=gv)
        )
        self._historial[visitante].append(
            _RegistroEquipo(puntos_de(gv, gl), goles_favor=gv, goles_contra=gl)
        )
        self._ultimo_partido[local] = partido.fecha
        self._ultimo_partido[visitante] = partido.fecha

        clave, invertido = _clave_h2h(local, visitante)
        if gl > gv:
            simbolo = "V" if invertido else "L"
        elif gl < gv:
            simbolo = "L" if invertido else "V"
        else:
            simbolo = "E"
        self._h2h[clave].append(simbolo)

        self._elo[local], self._elo[visitante] = actualizar_elo(
            self._elo[local], self._elo[visitante], gl, gv
        )
        self._partidos_registrados += 1

    @property
    def partidos_registrados(self) -> int:
        return self._partidos_registrados

    def ratings(self) -> dict[int, float]:
        return dict(self._elo)

    # --- internos ---

    def _forma(self, equipo_id: int) -> float:
        """Puntos sumados en los ultimos partidos (0 a 15 con ventana de 5)."""
        return float(sum(r.puntos for r in self._historial[equipo_id]))

    def _promedio(self, equipo_id: int, campo: str) -> float:
        historial = self._historial[equipo_id]
        if not historial:
            return 0.0
        return sum(getattr(r, campo) for r in historial) / len(historial)

    def _dias_descanso(self, equipo_id: int, fecha: datetime) -> float:
        anterior = self._ultimo_partido.get(equipo_id)
        if anterior is None:
            return DIAS_DESCANSO_POR_DEFECTO
        dias = (fecha - anterior).total_seconds() / 86400.0
        return float(min(max(dias, 0.0), DIAS_DESCANSO_MAXIMO))

    def _h2h_desde(self, local: int, visitante: int) -> tuple[int, int, int]:
        """(victorias del local actual, empates, victorias del visitante actual)."""
        clave, invertido = _clave_h2h(local, visitante)
        historial = self._h2h.get(clave)
        if not historial:
            return 0, 0, 0
        victorias_menor = sum(1 for s in historial if s == "L")
        victorias_mayor = sum(1 for s in historial if s == "V")
        empates = sum(1 for s in historial if s == "E")
        if invertido:
            return victorias_mayor, empates, victorias_menor
        return victorias_menor, empates, victorias_mayor


def _clave_h2h(local: int, visitante: int) -> tuple[tuple[int, int], bool]:
    """Clave simetrica del cruce; `invertido` indica si hay que dar vuelta la optica.

    Los simbolos guardados ("L"/"V") son siempre desde la optica del equipo con
    id menor, para que da igual quien juego de local en cada enfrentamiento.
    """
    if local <= visitante:
        return (local, visitante), False
    return (visitante, local), True


def resultado_de(partido: PartidoHistorico) -> str | None:
    """Etiqueta objetivo: 'L', 'E' o 'V'."""
    if not partido.finalizado:
        return None
    if partido.goles_local > partido.goles_visitante:
        return "L"
    if partido.goles_local < partido.goles_visitante:
        return "V"
    return "E"
