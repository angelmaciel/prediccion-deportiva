"""Escenarios simples y combinados sobre la matriz de marcadores.

El punto central: una combinada NO es el producto de sus partes. Estos tests
fijan esa propiedad, porque es justamente lo que un calculo apurado rompe.
"""

from __future__ import annotations

import pytest

from app.ml.mercados import (
    COMBINACIONES,
    ESCENARIOS,
    combinadas,
    etiqueta_combinada,
    probabilidad,
    simples,
)
from app.ml.poisson import ModeloPoissonBivariado, pmf_bivariada


def matriz_desde(celdas: dict[tuple[int, int], float], tamanio: int = 4) -> list[list[float]]:
    """Matriz chica y explicita: cada test dice exactamente que marcadores hay."""
    matriz = [[0.0] * tamanio for _ in range(tamanio)]
    for (x, y), valor in celdas.items():
        matriz[x][y] = valor
    return matriz


class TestCondiciones:
    @pytest.mark.parametrize(
        "clave,marcador,esperado",
        [
            ("local", (2, 1), True),
            ("local", (1, 1), False),
            ("empate", (0, 0), True),
            ("visitante", (0, 3), True),
            ("local_o_empate", (1, 1), True),
            ("local_o_empate", (0, 1), False),
            ("mas_2_5", (2, 1), True),
            ("mas_2_5", (1, 1), False),
            ("menos_2_5", (1, 1), True),
            ("ambos_marcan", (1, 1), True),
            ("ambos_marcan", (3, 0), False),
            ("local_sin_recibir", (2, 0), True),
            ("local_por_dos", (3, 1), True),
            ("local_por_dos", (2, 1), False),
        ],
    )
    def test_cada_escenario_reconoce_su_marcador(self, clave, marcador, esperado):
        assert ESCENARIOS[clave].condicion(*marcador) is esperado


class TestProbabilidadSimple:
    def test_suma_las_celdas_que_cumplen(self):
        matriz = matriz_desde({(2, 0): 0.3, (1, 1): 0.5, (0, 2): 0.2})
        assert probabilidad(matriz, "local") == pytest.approx(0.3)
        assert probabilidad(matriz, "empate") == pytest.approx(0.5)
        assert probabilidad(matriz, "visitante") == pytest.approx(0.2)

    def test_1x2_es_una_particion(self):
        """Los tres resultados son exhaustivos y excluyentes: tienen que dar 1."""
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        total = sum(probabilidad(matriz, c) for c in ("local", "empate", "visitante"))
        assert total == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "a,b",
        [
            ("mas_2_5", "menos_2_5"),
            ("mas_1_5", "menos_1_5"),
            ("ambos_marcan", "no_ambos_marcan"),
            ("sin_empate", "empate"),
        ],
    )
    def test_los_complementarios_suman_uno(self, a, b):
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        assert probabilidad(matriz, a) + probabilidad(matriz, b) == pytest.approx(1.0)

    def test_ordena_de_mayor_a_menor(self):
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        resultados = simples(matriz)
        probabilidades = [r.probabilidad for r in resultados]
        assert probabilidades == sorted(probabilidades, reverse=True)


class TestCombinadas:
    def test_la_conjunta_exige_las_dos_condiciones(self):
        matriz = matriz_desde({(2, 0): 0.4, (2, 1): 0.3, (1, 1): 0.3})
        # Gana el local: (2,0) y (2,1) = 0.7. Con mas de 2.5 goles: solo (2,1).
        assert probabilidad(matriz, "local") == pytest.approx(0.7)
        assert probabilidad(matriz, "local", "mas_2_5") == pytest.approx(0.3)

    def test_nunca_supera_a_sus_partes(self):
        """P(A y B) <= min(P(A), P(B)) siempre. Si esto falla, el calculo miente."""
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        for claves in COMBINACIONES:
            conjunta = probabilidad(matriz, *claves)
            for clave in claves:
                assert conjunta <= probabilidad(matriz, clave) + 1e-12

    def test_la_conjunta_no_es_el_producto(self):
        """El caso que motiva todo el modulo: los eventos estan correlacionados."""
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        conjunta = probabilidad(matriz, "local", "mas_2_5")
        producto = probabilidad(matriz, "local") * probabilidad(matriz, "mas_2_5")
        assert conjunta != pytest.approx(producto, abs=1e-4)

    def test_reporta_la_brecha_contra_el_producto(self):
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        resultado = next(r for r in combinadas(matriz) if r.claves == ("local", "mas_2_5"))
        assert resultado.probabilidad_ingenua is not None
        assert resultado.correlacion == pytest.approx(
            resultado.probabilidad - resultado.probabilidad_ingenua
        )

    def test_las_condiciones_incompatibles_no_se_muestran(self):
        matriz = matriz_desde({(1, 1): 1.0})
        # Con el marcador siempre 1-1, "gana el local" es imposible.
        assert probabilidad(matriz, "local", "mas_2_5") == pytest.approx(0.0)
        assert all(r.probabilidad > 0 for r in combinadas(matriz))

    def test_una_combinada_de_tres_sigue_siendo_coherente(self):
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        triple = probabilidad(matriz, "local", "mas_1_5", "ambos_marcan")
        doble = probabilidad(matriz, "local", "ambos_marcan")
        assert triple <= doble + 1e-12

    def test_ordena_de_mayor_a_menor(self):
        matriz = ModeloPoissonBivariado().matriz_marcadores(1, 2)
        probabilidades = [r.probabilidad for r in combinadas(matriz)]
        assert probabilidades == sorted(probabilidades, reverse=True)

    def test_la_etiqueta_describe_las_dos_partes(self):
        assert etiqueta_combinada("local", "mas_2_5") == "Gana el local + Mas de 2.5 goles"


class TestCoherenciaConElPoisson:
    def test_coincide_con_el_1x2_del_modelo(self):
        """Los escenarios y `probabilidades_1x2` leen la misma matriz."""
        modelo = ModeloPoissonBivariado()
        matriz = modelo.matriz_marcadores(1, 2)
        local, empate, visitante = modelo.probabilidades_1x2(1, 2)

        assert probabilidad(matriz, "local") == pytest.approx(local)
        assert probabilidad(matriz, "empate") == pytest.approx(empate)
        assert probabilidad(matriz, "visitante") == pytest.approx(visitante)

    def test_mas_goles_esperados_sube_el_over(self):
        """Sanidad: si suben las tasas, sube la probabilidad de partido con goles."""
        pocos = [[pmf_bivariada(x, y, 0.6, 0.5, 0.0) for y in range(9)] for x in range(9)]
        muchos = [[pmf_bivariada(x, y, 2.4, 2.0, 0.0) for y in range(9)] for x in range(9)]
        assert probabilidad(muchos, "mas_2_5") > probabilidad(pocos, "mas_2_5")
