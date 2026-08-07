"""Modelo de Poisson bivariado para marcador exacto.

Por que Poisson: los goles de un partido de futbol se aproximan bien con un
proceso de conteo de tasa baja. La version *bivariada* agrega un termino comun
`lambda3` que captura la covarianza positiva entre los goles de ambos equipos
(partidos abiertos vs. trabados). Un Poisson doble independiente subestima
sistematicamente los empates; el termino compartido corrige parte de eso.

La fuerza de ataque y defensa de cada equipo se estima por el metodo de
razones sobre el promedio de la liga: simple, estable con pocos datos y sin
optimizacion numerica que pueda no converger en produccion.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.ml.features import PartidoHistorico

MAX_GOLES = 8  # el truncamiento deja fuera <0.1% de la masa de probabilidad
FUERZA_MINIMA = 0.2
FUERZA_MAXIMA = 3.0
LAMBDA_MINIMO = 0.05


@dataclass
class ParametrosPoisson:
    media_goles_local: float = 1.5
    media_goles_visitante: float = 1.1
    ataque: dict[int, float] = field(default_factory=dict)
    defensa: dict[int, float] = field(default_factory=dict)
    lambda_comun: float = 0.0
    partidos_usados: int = 0


class ModeloPoissonBivariado:
    def __init__(self) -> None:
        self.parametros = ParametrosPoisson()
        self.ajustado = False

    def ajustar(self, partidos: list[PartidoHistorico]) -> ParametrosPoisson:
        finalizados = [p for p in partidos if p.finalizado]
        if not finalizados:
            self.ajustado = False
            return self.parametros

        media_local = sum(p.goles_local for p in finalizados) / len(finalizados)
        media_visitante = sum(p.goles_visitante for p in finalizados) / len(finalizados)
        media_local = max(media_local, LAMBDA_MINIMO)
        media_visitante = max(media_visitante, LAMBDA_MINIMO)

        marcados: dict[int, list[int]] = defaultdict(list)
        recibidos: dict[int, list[int]] = defaultdict(list)
        # Se normaliza por la media del rol (local/visitante) que ocupaba el equipo,
        # asi la ventaja de localia no se confunde con calidad ofensiva.
        for p in finalizados:
            marcados[p.equipo_local_id].append(p.goles_local / media_local)
            recibidos[p.equipo_local_id].append(p.goles_visitante / media_visitante)
            marcados[p.equipo_visitante_id].append(p.goles_visitante / media_visitante)
            recibidos[p.equipo_visitante_id].append(p.goles_local / media_local)

        ataque = {e: _acotar(_media(v)) for e, v in marcados.items()}
        defensa = {e: _acotar(_media(v)) for e, v in recibidos.items()}

        self.parametros = ParametrosPoisson(
            media_goles_local=media_local,
            media_goles_visitante=media_visitante,
            ataque=ataque,
            defensa=defensa,
            lambda_comun=_estimar_lambda_comun(finalizados, media_local, media_visitante),
            partidos_usados=len(finalizados),
        )
        self.ajustado = True
        return self.parametros

    def lambdas(self, equipo_local_id: int, equipo_visitante_id: int) -> tuple[float, float, float]:
        """Tasas esperadas (local, visitante, comun) para un cruce."""
        p = self.parametros
        ataque_local = p.ataque.get(equipo_local_id, 1.0)
        defensa_local = p.defensa.get(equipo_local_id, 1.0)
        ataque_visitante = p.ataque.get(equipo_visitante_id, 1.0)
        defensa_visitante = p.defensa.get(equipo_visitante_id, 1.0)

        lambda_local = max(ataque_local * defensa_visitante * p.media_goles_local, LAMBDA_MINIMO)
        lambda_visitante = max(
            ataque_visitante * defensa_local * p.media_goles_visitante, LAMBDA_MINIMO
        )
        # lambda3 es la parte comun: se descuenta de las tasas propias para no
        # inflar el total de goles esperado.
        comun = min(p.lambda_comun, lambda_local * 0.9, lambda_visitante * 0.9)
        return lambda_local - comun, lambda_visitante - comun, comun

    def matriz_marcadores(
        self, equipo_local_id: int, equipo_visitante_id: int, max_goles: int = MAX_GOLES
    ) -> list[list[float]]:
        l1, l2, l3 = self.lambdas(equipo_local_id, equipo_visitante_id)
        matriz = [
            [pmf_bivariada(x, y, l1, l2, l3) for y in range(max_goles + 1)]
            for x in range(max_goles + 1)
        ]
        # Renormaliza para compensar la cola truncada.
        total = sum(sum(fila) for fila in matriz)
        if total > 0:
            matriz = [[v / total for v in fila] for fila in matriz]
        return matriz

    def probabilidades_1x2(
        self, equipo_local_id: int, equipo_visitante_id: int
    ) -> tuple[float, float, float]:
        matriz = self.matriz_marcadores(equipo_local_id, equipo_visitante_id)
        local = sum(matriz[x][y] for x in range(len(matriz)) for y in range(x))
        empate = sum(matriz[i][i] for i in range(len(matriz)))
        visitante = sum(
            matriz[x][y] for x in range(len(matriz)) for y in range(x + 1, len(matriz[x]))
        )
        return local, empate, visitante

    def marcador_mas_probable(
        self, equipo_local_id: int, equipo_visitante_id: int
    ) -> tuple[int, int, float]:
        matriz = self.matriz_marcadores(equipo_local_id, equipo_visitante_id)
        mejor = (0, 0, 0.0)
        for x, fila in enumerate(matriz):
            for y, prob in enumerate(fila):
                if prob > mejor[2]:
                    mejor = (x, y, prob)
        return mejor


def pmf_bivariada(x: int, y: int, l1: float, l2: float, l3: float) -> float:
    """P(X=x, Y=y) del Poisson bivariado con termino comun l3.

    Con l3 = 0 colapsa al producto de dos Poisson independientes.
    """
    if x < 0 or y < 0:
        return 0.0
    base = math.exp(-(l1 + l2 + l3))
    try:
        base *= (l1**x) / math.factorial(x) * (l2**y) / math.factorial(y)
    except OverflowError:  # pragma: no cover - solo con lambdas absurdos
        return 0.0
    if l3 <= 0 or l1 <= 0 or l2 <= 0:
        return base
    suma = 0.0
    for k in range(min(x, y) + 1):
        suma += (
            math.comb(x, k) * math.comb(y, k) * math.factorial(k) * (l3 / (l1 * l2)) ** k
        )
    return base * suma


def _media(valores: list[float]) -> float:
    return sum(valores) / len(valores) if valores else 1.0


def _acotar(valor: float) -> float:
    """Evita que un equipo con 2 partidos raros genere lambdas disparatados."""
    return min(max(valor, FUERZA_MINIMA), FUERZA_MAXIMA)


def _estimar_lambda_comun(
    partidos: list[PartidoHistorico], media_local: float, media_visitante: float
) -> float:
    """Covarianza empirica entre goles de local y visitante, acotada a >= 0.

    En el Poisson bivariado, Cov(X, Y) = lambda3 exactamente.
    """
    n = len(partidos)
    if n < 2:
        return 0.0
    covarianza = (
        sum(
            (p.goles_local - media_local) * (p.goles_visitante - media_visitante)
            for p in partidos
        )
        / n
    )
    # Una covarianza negativa no es representable con este modelo; se trunca a 0.
    return max(0.0, min(covarianza, 0.5))
