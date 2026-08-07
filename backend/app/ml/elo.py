"""Ranking Elo calculado internamente, actualizado partido a partido.

Variante del Elo de futbol (World Football Elo Ratings): la expectativa
incorpora la ventaja de localia como puntos extra, y el ajuste se amplifica
segun la diferencia de goles, para que una goleada mueva mas el rating que un
1-0 sufrido.

Funciones puras y sin dependencias de base de datos, para poder testearlas
aisladas y reusarlas tanto en el entrenamiento como en la inferencia.
"""

from __future__ import annotations

ELO_INICIAL = 1500.0
K_BASE = 20.0
# ~65 puntos de Elo equivalen a la ventaja de jugar de local en ligas top.
VENTAJA_LOCAL = 65.0


def esperanza_local(
    elo_local: float, elo_visitante: float, ventaja_local: float = VENTAJA_LOCAL
) -> float:
    """Probabilidad esperada (0..1) del local, contando puntaje de empate como 0.5."""
    diferencia = (elo_visitante - (elo_local + ventaja_local)) / 400.0
    return 1.0 / (1.0 + 10.0**diferencia)


def multiplicador_diferencia_goles(diferencia_goles: int) -> float:
    """Amplifica el ajuste cuando el resultado es contundente."""
    dg = abs(diferencia_goles)
    if dg <= 1:
        return 1.0
    if dg == 2:
        return 1.5
    return (11.0 + dg) / 8.0


def puntaje_local(goles_local: int, goles_visitante: int) -> float:
    if goles_local > goles_visitante:
        return 1.0
    if goles_local < goles_visitante:
        return 0.0
    return 0.5


def actualizar_elo(
    elo_local: float,
    elo_visitante: float,
    goles_local: int,
    goles_visitante: int,
    k: float = K_BASE,
    ventaja_local: float = VENTAJA_LOCAL,
) -> tuple[float, float]:
    """Devuelve los ratings actualizados (local, visitante) tras un partido.

    El sistema es de suma cero: lo que gana uno lo pierde el otro.
    """
    esperado = esperanza_local(elo_local, elo_visitante, ventaja_local)
    obtenido = puntaje_local(goles_local, goles_visitante)
    ajuste = (
        k
        * multiplicador_diferencia_goles(goles_local - goles_visitante)
        * (obtenido - esperado)
    )
    return elo_local + ajuste, elo_visitante - ajuste
