"""Calculo de features y Elo.

El test mas importante del archivo es `test_no_hay_fuga_de_informacion`: si eso
se rompe, todas las metricas del producto pasan a ser mentira.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ml.elo import (
    ELO_INICIAL,
    actualizar_elo,
    esperanza_local,
    multiplicador_diferencia_goles,
    puntaje_local,
)
from app.ml.features import (
    NOMBRES_FEATURES,
    VENTANA_FORMA,
    CalculadoraFeatures,
    PartidoHistorico,
    puntos_de,
    resultado_de,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def partido(id_, local, visitante, dia, gl=None, gv=None) -> PartidoHistorico:
    return PartidoHistorico(
        id=id_,
        equipo_local_id=local,
        equipo_visitante_id=visitante,
        fecha=BASE + timedelta(days=dia),
        goles_local=gl,
        goles_visitante=gv,
    )


class TestElo:
    def test_equipos_iguales_esperanza_favorece_al_local(self):
        # Con ratings iguales, la ventaja de localia debe inclinar la balanza.
        assert esperanza_local(1500, 1500) > 0.5

    def test_esperanza_crece_con_la_diferencia(self):
        assert esperanza_local(1700, 1400) > esperanza_local(1500, 1400)

    def test_esperanza_en_rango_valido(self):
        for local, visitante in [(1000, 2000), (2000, 1000), (1500, 1500)]:
            assert 0.0 < esperanza_local(local, visitante) < 1.0

    def test_suma_cero(self):
        nuevo_local, nuevo_visitante = actualizar_elo(1500, 1500, 2, 0)
        assert nuevo_local + nuevo_visitante == pytest.approx(3000.0)

    def test_ganar_sube_y_perder_baja(self):
        nuevo_local, nuevo_visitante = actualizar_elo(1500, 1500, 3, 0)
        assert nuevo_local > 1500 > nuevo_visitante

    def test_empate_penaliza_al_favorito(self):
        # El local mucho mejor rankeado pierde puntos al empatar.
        nuevo_local, _ = actualizar_elo(1800, 1400, 1, 1)
        assert nuevo_local < 1800

    def test_goleada_mueve_mas_que_triunfo_ajustado(self):
        ajustado, _ = actualizar_elo(1500, 1500, 1, 0)
        goleada, _ = actualizar_elo(1500, 1500, 5, 0)
        assert goleada > ajustado

    def test_multiplicador_monotono(self):
        assert multiplicador_diferencia_goles(1) == 1.0
        assert multiplicador_diferencia_goles(2) == 1.5
        assert multiplicador_diferencia_goles(4) > multiplicador_diferencia_goles(3)
        # Es simetrico: da igual quien gano por esa diferencia.
        assert multiplicador_diferencia_goles(-3) == multiplicador_diferencia_goles(3)

    def test_puntaje_local(self):
        assert puntaje_local(2, 1) == 1.0
        assert puntaje_local(1, 1) == 0.5
        assert puntaje_local(0, 3) == 0.0


class TestPuntos:
    def test_asignacion(self):
        assert puntos_de(2, 1) == 3
        assert puntos_de(1, 1) == 1
        assert puntos_de(0, 1) == 0


class TestCalculadoraFeatures:
    def test_estado_inicial_neutro(self):
        calc = CalculadoraFeatures()
        f = calc.features_de(partido(1, 10, 20, 0))
        assert f["elo_local"] == ELO_INICIAL
        assert f["elo_visitante"] == ELO_INICIAL
        assert f["forma_reciente_local"] == 0.0
        assert f["h2h_local_wins"] == 0
        assert f["dias_descanso_local"] == 7.0  # valor por defecto sin historial

    def test_todas_las_features_declaradas_estan_presentes(self):
        calc = CalculadoraFeatures()
        f = calc.features_de(partido(1, 10, 20, 0))
        assert set(f) == set(NOMBRES_FEATURES)
        assert len(calc.vector_de(partido(1, 10, 20, 0))) == len(NOMBRES_FEATURES)

    def test_vector_respeta_el_orden_declarado(self):
        calc = CalculadoraFeatures()
        p = partido(1, 10, 20, 0)
        f = calc.features_de(p)
        assert calc.vector_de(p) == [f[n] for n in NOMBRES_FEATURES]

    def test_no_hay_fuga_de_informacion(self):
        """Las features de un partido no pueden depender de su propio resultado.

        Se calculan las features del mismo partido con dos marcadores opuestos:
        si el estado previo es el mismo, el vector tiene que ser identico.
        """
        historia = [partido(1, 10, 20, 0, 1, 0), partido(2, 30, 40, 1, 2, 2)]

        vectores = []
        for gl, gv in [(5, 0), (0, 5)]:
            calc = CalculadoraFeatures()
            for p in historia:
                calc.features_de(p)
                calc.registrar(p)
            vectores.append(calc.vector_de(partido(3, 10, 20, 5, gl, gv)))

        assert vectores[0] == vectores[1]

    def test_registrar_actualiza_forma(self):
        calc = CalculadoraFeatures()
        p = partido(1, 10, 20, 0, 3, 0)
        calc.registrar(p)
        f = calc.features_de(partido(2, 10, 20, 7))
        assert f["forma_reciente_local"] == 3.0  # victoria = 3 puntos
        assert f["forma_reciente_visitante"] == 0.0

    def test_forma_usa_ventana_movil(self):
        """Solo los ultimos VENTANA_FORMA partidos cuentan."""
        calc = CalculadoraFeatures()
        # Mas victorias que la ventana: la forma satura en 3 * VENTANA_FORMA.
        for i in range(VENTANA_FORMA + 3):
            calc.registrar(partido(i + 1, 10, 20 + i, i, 1, 0))
        f = calc.features_de(partido(100, 10, 99, 20))
        assert f["forma_reciente_local"] == 3.0 * VENTANA_FORMA

    def test_partido_sin_resultado_no_altera_el_estado(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0))  # sin goles: aun no se jugo
        assert calc.partidos_registrados == 0
        assert calc.elo(10) == ELO_INICIAL

    def test_h2h_se_acumula_y_respeta_la_optica(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 2, 0))  # gana 10 de local
        calc.registrar(partido(2, 20, 10, 7, 0, 1))  # gana 10 de visitante

        f = calc.features_de(partido(3, 10, 20, 14))
        assert (f["h2h_local_wins"], f["h2h_draws"], f["h2h_away_wins"]) == (2.0, 0.0, 0.0)

        # Con los roles invertidos, las columnas se dan vuelta.
        g = calc.features_de(partido(4, 20, 10, 14))
        assert (g["h2h_local_wins"], g["h2h_draws"], g["h2h_away_wins"]) == (0.0, 0.0, 2.0)

    def test_h2h_no_mezcla_rivales(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 3, 0))
        f = calc.features_de(partido(2, 10, 30, 7))  # rival distinto
        assert f["h2h_local_wins"] == 0.0

    def test_dias_descanso(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 1, 1))
        f = calc.features_de(partido(2, 10, 30, 3))
        assert f["dias_descanso_local"] == pytest.approx(3.0)
        assert f["dias_descanso_visitante"] == 7.0  # el 30 no jugo todavia

    def test_dias_descanso_tiene_techo(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 1, 1))
        f = calc.features_de(partido(2, 10, 30, 200))
        assert f["dias_descanso_local"] == 30.0

    def test_promedios_de_goles(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 3, 1))
        calc.registrar(partido(2, 10, 30, 7, 1, 1))
        f = calc.features_de(partido(3, 10, 40, 14))
        assert f["goles_favor_local"] == pytest.approx(2.0)  # (3 + 1) / 2
        assert f["goles_contra_local"] == pytest.approx(1.0)  # (1 + 1) / 2

    def test_elo_se_propaga_a_las_features(self):
        calc = CalculadoraFeatures()
        calc.registrar(partido(1, 10, 20, 0, 4, 0))
        f = calc.features_de(partido(2, 10, 20, 7))
        assert f["elo_local"] > ELO_INICIAL > f["elo_visitante"]


class TestResultado:
    @pytest.mark.parametrize(
        "gl,gv,esperado", [(2, 0, "L"), (1, 1, "E"), (0, 3, "V"), (None, None, None)]
    )
    def test_etiqueta(self, gl, gv, esperado):
        assert resultado_de(partido(1, 10, 20, 0, gl, gv)) == esperado
