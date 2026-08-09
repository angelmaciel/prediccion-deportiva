"""La ventana por defecto de los listados publicos: ayer, hoy y manana.

Traer temporadas enteras en cada visita es lo que hacia lenta la carga. Estos
tests fijan el contrato: sin pedirlo, el backend devuelve solo la fecha; el
historico completo sigue accesible pero hay que pedirlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.servicios.metricas import recalcular_metricas_por_jornada, resumen_global
from app.servicios.ventana import ventana_reciente
from tests.conftest import crear_partido


def _dias(n: int) -> datetime:
    """Mediodia UTC de hace/dentro de `n` dias, lejos del borde del dia."""
    ahora = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    return ahora + timedelta(days=n)


class TestVentanaReciente:
    def test_cubre_ayer_hoy_y_manana(self):
        ahora = datetime(2026, 8, 9, 17, 30, tzinfo=timezone.utc)
        inicio, fin = ventana_reciente(ahora=ahora)
        assert inicio == datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
        assert fin == datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)

    def test_corta_por_dia_calendario_no_por_24_horas(self):
        """A cualquier hora del dia la ventana es la misma: la lista no se mueve sola."""
        temprano = ventana_reciente(ahora=datetime(2026, 8, 9, 0, 5, tzinfo=timezone.utc))
        tarde = ventana_reciente(ahora=datetime(2026, 8, 9, 23, 55, tzinfo=timezone.utc))
        assert temprano == tarde


class TestListadoDePartidos:
    @pytest.fixture
    def sembrado(self, db, equipos):
        """Un partido viejo, uno de ayer y uno de manana."""
        return {
            "viejo": crear_partido(db, equipos[0], equipos[1], _dias(-40), 2, 0, externo="viejo"),
            "ayer": crear_partido(db, equipos[2], equipos[3], _dias(-1), 1, 1, externo="ayer"),
            "manana": crear_partido(db, equipos[4], equipos[5], _dias(1), externo="manana"),
        }

    def test_por_defecto_solo_trae_la_ventana(self, cliente, sembrado):
        cuerpo = cliente.get("/partidos").json()
        ids = {p["id"] for p in cuerpo["items"]}
        assert ids == {sembrado["ayer"].id, sembrado["manana"].id}
        assert cuerpo["total"] == 2

    def test_historico_trae_todo(self, cliente, sembrado):
        cuerpo = cliente.get("/partidos", params={"historico": "true"}).json()
        assert cuerpo["total"] == 3
        assert sembrado["viejo"].id in {p["id"] for p in cuerpo["items"]}

    def test_un_rango_explicito_manda_sobre_la_ventana(self, cliente, sembrado):
        """Pedir `desde` ya es consultar el historico: no se le superpone la ventana."""
        cuerpo = cliente.get("/partidos", params={"desde": _dias(-60).isoformat()}).json()
        assert cuerpo["total"] == 3

    def test_resultados_por_defecto_no_muestran_partidos_viejos(self, cliente, sembrado):
        cuerpo = cliente.get("/partidos", params={"estado": "finalizado"}).json()
        assert [p["id"] for p in cuerpo["items"]] == [sembrado["ayer"].id]


class TestProximos:
    def test_incluye_ayer_y_manana_pero_no_mas_lejos(self, cliente, db, equipos):
        ayer = crear_partido(db, equipos[0], equipos[1], _dias(-1), externo="prog-ayer")
        manana = crear_partido(db, equipos[2], equipos[3], _dias(1), externo="prog-manana")
        crear_partido(db, equipos[4], equipos[5], _dias(5), externo="prog-lejos")

        ids = {p["id"] for p in cliente.get("/partidos/proximos").json()}
        assert ids == {ayer.id, manana.id}

    def test_dias_amplia_la_ventana_hacia_los_dos_lados(self, cliente, db, equipos):
        lejos = crear_partido(db, equipos[4], equipos[5], _dias(5), externo="prog-lejos")
        ids = {p["id"] for p in cliente.get("/partidos/proximos", params={"dias": 7}).json()}
        assert lejos.id in ids


class TestTransparencia:
    @pytest.fixture
    def con_predicciones(self, db, equipos):
        from app.modelos.prediccion import Prediccion

        viejo = crear_partido(db, equipos[0], equipos[1], _dias(-40), 2, 0, externo="t-viejo")
        ayer = crear_partido(db, equipos[2], equipos[3], _dias(-1), 0, 2, externo="t-ayer")
        for partido in (viejo, ayer):
            db.add(
                Prediccion(
                    partido_id=partido.id,
                    prob_local=0.6,
                    prob_empate=0.2,
                    prob_visitante=0.2,
                    modelo_version="v-test",
                )
            )
        db.commit()
        return viejo, ayer

    def test_el_resumen_por_defecto_solo_evalua_la_ventana(self, cliente, con_predicciones):
        cuerpo = cliente.get("/transparencia/resumen").json()
        assert cuerpo["partidos_evaluados"] == 1

    def test_el_resumen_historico_evalua_todo(self, cliente, con_predicciones):
        cuerpo = cliente.get("/transparencia/resumen", params={"historico": "true"}).json()
        assert cuerpo["partidos_evaluados"] == 2

    def test_resumen_global_sin_ventana_sigue_recorriendo_todo(self, db, con_predicciones):
        """El calculo interno (jobs, backtest) no cambia: la ventana es opt-in."""
        assert resumen_global(db).partidos_evaluados == 2

    def test_las_jornadas_se_acotan_a_las_que_jugaron_en_la_ventana(
        self, cliente, db, con_predicciones
    ):
        """`metricas_jornada` no guarda fecha: se filtra por los partidos de cada jornada."""
        viejo, ayer = con_predicciones
        # Jornadas distintas para que cada partido caiga en su propia fila.
        viejo.jornada, ayer.jornada = 3, 27
        db.commit()
        assert recalcular_metricas_por_jornada(db) == 2

        recientes = cliente.get("/transparencia/jornadas").json()
        assert [m["jornada"] for m in recientes] == [27]

        todas = cliente.get("/transparencia/jornadas", params={"historico": "true"}).json()
        assert sorted(m["jornada"] for m in todas) == [3, 27]
