"""Escenarios simples y combinados derivados de la matriz de marcadores.

La idea que sostiene todo el modulo: cada escenario ("gana el local", "mas de
2.5 goles", "ambos marcan") es una **condicion sobre el marcador final**, y la
matriz del Poisson bivariado ya asigna probabilidad a cada marcador posible.
Entonces la probabilidad de un escenario es la suma de las celdas que lo
cumplen, y la de una combinacion es la suma de las celdas que cumplen *todas*
las condiciones a la vez.

Por que importa hacerlo asi y no multiplicar: "gana el local" y "mas de 2.5
goles" no son independientes — un partido con muchos goles suele ser uno en el
que alguien se impuso. Multiplicar las marginales da un numero optimista que no
existe. Sumar sobre la matriz respeta la correlacion sin suponer nada.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

Condicion = Callable[[int, int], bool]


@dataclass(frozen=True, slots=True)
class Escenario:
    clave: str
    etiqueta: str
    condicion: Condicion


# Cada escenario se define una sola vez y sirve tanto suelto como combinado.
ESCENARIOS: dict[str, Escenario] = {
    e.clave: e
    for e in (
        Escenario("local", "Gana el local", lambda x, y: x > y),
        Escenario("empate", "Empate", lambda x, y: x == y),
        Escenario("visitante", "Gana el visitante", lambda x, y: x < y),
        Escenario("local_o_empate", "El local no pierde", lambda x, y: x >= y),
        Escenario("visitante_o_empate", "El visitante no pierde", lambda x, y: x <= y),
        Escenario("sin_empate", "No termina empatado", lambda x, y: x != y),
        Escenario("mas_1_5", "Mas de 1.5 goles", lambda x, y: x + y > 1),
        Escenario("menos_1_5", "Menos de 1.5 goles", lambda x, y: x + y < 2),
        Escenario("mas_2_5", "Mas de 2.5 goles", lambda x, y: x + y > 2),
        Escenario("menos_2_5", "Menos de 2.5 goles", lambda x, y: x + y < 3),
        Escenario("mas_3_5", "Mas de 3.5 goles", lambda x, y: x + y > 3),
        Escenario("menos_3_5", "Menos de 3.5 goles", lambda x, y: x + y < 4),
        Escenario("ambos_marcan", "Ambos marcan", lambda x, y: x > 0 and y > 0),
        Escenario("no_ambos_marcan", "No marcan los dos", lambda x, y: x == 0 or y == 0),
        Escenario("local_sin_recibir", "El local no recibe goles", lambda x, y: y == 0),
        Escenario("visitante_sin_recibir", "El visitante no recibe goles", lambda x, y: x == 0),
        Escenario("local_por_dos", "El local gana por dos o mas", lambda x, y: x - y >= 2),
        Escenario("visitante_por_dos", "El visitante gana por dos o mas", lambda x, y: y - x >= 2),
    )
}

# Combinaciones que tienen sentido leer juntas. Se excluyen a proposito las
# redundantes ("gana el local" + "el local no pierde") y las imposibles
# ("empate" + "gana el local"), que darian 0 y solo ensucian la lista.
COMBINACIONES: tuple[tuple[str, ...], ...] = (
    ("local", "mas_2_5"),
    ("local", "menos_2_5"),
    ("local", "ambos_marcan"),
    ("local", "local_sin_recibir"),
    ("visitante", "mas_2_5"),
    ("visitante", "menos_2_5"),
    ("visitante", "ambos_marcan"),
    ("visitante", "visitante_sin_recibir"),
    ("empate", "menos_2_5"),
    ("empate", "ambos_marcan"),
    ("local_o_empate", "mas_1_5"),
    ("local_o_empate", "menos_3_5"),
    ("visitante_o_empate", "mas_1_5"),
    ("visitante_o_empate", "menos_3_5"),
    ("sin_empate", "mas_2_5"),
    ("ambos_marcan", "mas_2_5"),
    ("local", "mas_1_5", "ambos_marcan"),
    ("visitante", "mas_1_5", "ambos_marcan"),
)


def probabilidad(matriz: list[list[float]], *claves: str) -> float:
    """Masa de probabilidad de los marcadores que cumplen todas las condiciones."""
    condiciones = [ESCENARIOS[clave].condicion for clave in claves]
    total = 0.0
    for x, fila in enumerate(matriz):
        for y, celda in enumerate(fila):
            if celda and all(condicion(x, y) for condicion in condiciones):
                total += celda
    return total


def etiqueta_combinada(*claves: str) -> str:
    return " + ".join(ESCENARIOS[clave].etiqueta for clave in claves)


@dataclass(slots=True)
class ResultadoEscenario:
    claves: tuple[str, ...]
    etiqueta: str
    probabilidad: float
    # Solo en las combinadas: que daria multiplicar las marginales como si los
    # eventos fueran independientes. La brecha contra `probabilidad` es la
    # correlacion que el modelo captura y una multiplicacion ingenua se pierde.
    probabilidad_ingenua: float | None = None

    @property
    def correlacion(self) -> float | None:
        if self.probabilidad_ingenua is None:
            return None
        return self.probabilidad - self.probabilidad_ingenua


def simples(
    matriz: list[list[float]], claves: tuple[str, ...] | None = None
) -> list[ResultadoEscenario]:
    elegidas = claves if claves is not None else tuple(ESCENARIOS)
    resultados = [
        ResultadoEscenario(
            claves=(clave,),
            etiqueta=ESCENARIOS[clave].etiqueta,
            probabilidad=probabilidad(matriz, clave),
        )
        for clave in elegidas
    ]
    return sorted(resultados, key=lambda r: r.probabilidad, reverse=True)


def combinadas(
    matriz: list[list[float]], combinaciones: tuple[tuple[str, ...], ...] = COMBINACIONES
) -> list[ResultadoEscenario]:
    resultados = []
    for claves in combinaciones:
        conjunta = probabilidad(matriz, *claves)
        if conjunta <= 0:
            continue  # combinacion imposible: no se muestra
        ingenua = 1.0
        for clave in claves:
            ingenua *= probabilidad(matriz, clave)
        resultados.append(
            ResultadoEscenario(
                claves=claves,
                etiqueta=etiqueta_combinada(*claves),
                probabilidad=conjunta,
                probabilidad_ingenua=ingenua,
            )
        )
    return sorted(resultados, key=lambda r: r.probabilidad, reverse=True)
