"""Ingesta: parseo de las APIs externas, upsert y control de cuota."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.modelos.auditoria import ConsumoCuota
from app.modelos.futbol import EstadoPartido, Fuente, Partido, Resultado
from app.servicios.ingesta.api_football import _jornada, _parsear_fixture
from app.servicios.ingesta.cuota import ControlCuota, CuotaAgotada, LimitadorPorMinuto
from app.servicios.ingesta.football_data import _parsear_partido
from app.servicios.ingesta.sincronizacion import (
    calcular_resultado,
    guardar_partido,
    sincronizar_europa,
    sincronizar_paraguay,
)

PAYLOAD_FOOTBALL_DATA = {
    "id": 428001,
    "utcDate": "2026-08-15T14:00:00Z",
    "status": "FINISHED",
    "matchday": 3,
    "season": {"startDate": "2026-08-01", "endDate": "2027-05-30"},
    "homeTeam": {"id": 57, "name": "Arsenal FC", "tla": "ARS", "crest": "https://x/ars.png"},
    "awayTeam": {"id": 61, "name": "Chelsea FC", "tla": "CHE", "crest": "https://x/che.png"},
    "score": {"fullTime": {"home": 2, "away": 1}},
}

PAYLOAD_API_FOOTBALL = {
    "fixture": {
        "id": 998877,
        "date": "2026-08-20T23:00:00+00:00",
        "status": {"short": "FT"},
    },
    "league": {"name": "Primera Division", "country": "Paraguay", "round": "Regular Season - 12"},
    "teams": {
        "home": {"id": 1, "name": "Olimpia", "logo": "https://x/oli.png"},
        "away": {"id": 2, "name": "Cerro Porteno", "logo": "https://x/cer.png"},
    },
    "goals": {"home": 0, "away": 0},
}


class TestParseoFootballData:
    def test_partido_completo(self):
        crudo = _parsear_partido(PAYLOAD_FOOTBALL_DATA, "Premier League", "Inglaterra")
        assert crudo is not None
        assert crudo.external_id == "428001"
        assert crudo.estado == "finalizado"
        assert crudo.jornada == 3
        assert crudo.temporada == "2026/2027"
        assert (crudo.goles_local, crudo.goles_visitante) == (2, 1)
        assert crudo.local.nombre == "Arsenal FC"
        assert crudo.fecha == datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc)

    def test_partido_programado_sin_marcador(self):
        payload = {
            **PAYLOAD_FOOTBALL_DATA,
            "status": "TIMED",
            "score": {"fullTime": {"home": None, "away": None}},
        }
        crudo = _parsear_partido(payload, "Premier League", "Inglaterra")
        assert crudo.estado == "programado"
        assert crudo.goles_local is None

    def test_eliminatoria_sin_equipos_definidos_se_descarta(self):
        payload = {**PAYLOAD_FOOTBALL_DATA, "homeTeam": {"id": None, "name": None}}
        assert _parsear_partido(payload, "Champions League", "Europa") is None

    def test_payload_corrupto_no_explota(self):
        assert _parsear_partido({"id": 1}, "Premier League", "Inglaterra") is None

    @pytest.mark.parametrize(
        "estado_api,esperado",
        [
            ("SCHEDULED", "programado"),
            ("IN_PLAY", "en_juego"),
            ("FINISHED", "finalizado"),
            ("POSTPONED", "suspendido"),
            ("ESTADO_NUEVO_DESCONOCIDO", "programado"),
        ],
    )
    def test_mapeo_de_estados(self, estado_api, esperado):
        payload = {**PAYLOAD_FOOTBALL_DATA, "status": estado_api}
        assert _parsear_partido(payload, "Premier League", "Inglaterra").estado == esperado


class TestParseoApiFootball:
    def test_fixture_completo(self):
        crudo = _parsear_fixture(PAYLOAD_API_FOOTBALL, 2026)
        assert crudo is not None
        assert crudo.external_id == "998877"
        assert crudo.estado == "finalizado"
        assert crudo.jornada == 12
        assert crudo.liga == "Primera Division"
        assert (crudo.goles_local, crudo.goles_visitante) == (0, 0)
        assert crudo.visitante.nombre == "Cerro Porteno"

    def test_fixture_corrupto_no_explota(self):
        assert _parsear_fixture({"fixture": {}}, 2026) is None

    @pytest.mark.parametrize(
        "ronda,esperado",
        [
            ("Regular Season - 12", 12),
            ("Clausura - 5", 5),
            ("Final", None),
            (None, None),
        ],
    )
    def test_extraccion_de_jornada(self, ronda, esperado):
        assert _jornada(ronda) == esperado


class TestResultado:
    @pytest.mark.parametrize(
        "gl,gv,esperado",
        [
            (2, 1, Resultado.LOCAL),
            (1, 1, Resultado.EMPATE),
            (0, 3, Resultado.VISITANTE),
            (None, 1, None),
            (1, None, None),
        ],
    )
    def test_calculo(self, gl, gv, esperado):
        assert calcular_resultado(gl, gv) == esperado


class TestUpsert:
    def test_primera_carga_crea_equipos_y_partido(self, db):
        crudo = _parsear_partido(PAYLOAD_FOOTBALL_DATA, "Premier League", "Inglaterra")
        partido, nuevo = guardar_partido(db, crudo, Fuente.FOOTBALL_DATA)
        db.commit()

        assert nuevo is True
        assert partido.estado == EstadoPartido.FINALIZADO
        assert partido.resultado_real == Resultado.LOCAL
        assert partido.equipo_local.nombre == "Arsenal FC"

    def test_reingesta_actualiza_en_lugar_de_duplicar(self, db):
        programado = _parsear_partido(
            {
                **PAYLOAD_FOOTBALL_DATA,
                "status": "TIMED",
                "score": {"fullTime": {"home": None, "away": None}},
            },
            "Premier League",
            "Inglaterra",
        )
        guardar_partido(db, programado, Fuente.FOOTBALL_DATA)
        db.commit()

        finalizado = _parsear_partido(PAYLOAD_FOOTBALL_DATA, "Premier League", "Inglaterra")
        partido, nuevo = guardar_partido(db, finalizado, Fuente.FOOTBALL_DATA)
        db.commit()

        assert nuevo is False
        assert db.query(Partido).count() == 1
        assert partido.resultado_real == Resultado.LOCAL

    def test_un_partido_que_deja_de_estar_finalizado_pierde_el_resultado(self, db):
        """Si la API corrige un partido a 'suspendido', no puede quedar el resultado viejo."""
        guardar_partido(
            db,
            _parsear_partido(PAYLOAD_FOOTBALL_DATA, "Premier League", "Inglaterra"),
            Fuente.FOOTBALL_DATA,
        )
        db.commit()

        suspendido = _parsear_partido(
            {**PAYLOAD_FOOTBALL_DATA, "status": "POSTPONED"}, "Premier League", "Inglaterra"
        )
        partido, _ = guardar_partido(db, suspendido, Fuente.FOOTBALL_DATA)
        db.commit()

        assert partido.estado == EstadoPartido.SUSPENDIDO
        assert partido.resultado_real is None

    def test_fuentes_distintas_no_colisionan(self, db):
        """Mismo external_id en dos APIs son partidos distintos."""
        fd = _parsear_partido(PAYLOAD_FOOTBALL_DATA, "Premier League", "Inglaterra")
        af = _parsear_fixture(PAYLOAD_API_FOOTBALL, 2026)
        af.external_id = fd.external_id

        guardar_partido(db, fd, Fuente.FOOTBALL_DATA)
        guardar_partido(db, af, Fuente.API_FOOTBALL)
        db.commit()
        assert db.query(Partido).count() == 2


class TestControlCuota:
    def test_arranca_con_la_cuota_completa(self, db):
        control = ControlCuota(db, Fuente.API_FOOTBALL, 100)
        assert control.restante() == 100

    def test_consumir_descuenta(self, db):
        control = ControlCuota(db, Fuente.API_FOOTBALL, 100)
        control.consumir(3)
        assert control.restante() == 97

    def test_verificar_falla_al_agotarse(self, db):
        control = ControlCuota(db, Fuente.API_FOOTBALL, 5)
        control.consumir(5)
        assert control.restante() == 0
        with pytest.raises(CuotaAgotada, match="Cuota diaria agotada"):
            control.verificar()

    def test_los_errores_se_contabilizan_aparte(self, db):
        control = ControlCuota(db, Fuente.API_FOOTBALL, 100)
        control.consumir(1, error=True)
        db.commit()
        registro = db.query(ConsumoCuota).one()
        assert registro.requests == 1
        assert registro.errores == 1

    def test_el_conteo_es_por_dia_y_fuente(self, db):
        ControlCuota(db, Fuente.API_FOOTBALL, 100).consumir(2)
        ControlCuota(db, Fuente.FOOTBALL_DATA, 100).consumir(5)
        db.commit()

        registros = {r.fuente: r.requests for r in db.query(ConsumoCuota).all()}
        assert registros[Fuente.API_FOOTBALL] == 2
        assert registros[Fuente.FOOTBALL_DATA] == 5

    def test_un_dia_anterior_no_descuenta_del_de_hoy(self, db):
        db.add(
            ConsumoCuota(fuente=Fuente.API_FOOTBALL, dia=date(2020, 1, 1), requests=100)
        )
        db.commit()
        assert ControlCuota(db, Fuente.API_FOOTBALL, 100).restante() == 100


class TestLimitadorPorMinuto:
    def test_no_bloquea_por_debajo_del_limite(self):
        limitador = LimitadorPorMinuto(10)
        for _ in range(10):
            limitador.esperar_turno()  # no debe dormir
        assert len(limitador._marcas) == 10


class ClienteEuropaFalso:
    """Cliente de football-data.org que registra con que rango se lo llamo."""

    def __init__(self):
        self.configurado = True
        self.llamadas = []

    def partidos_de_competicion(self, codigo, desde=None, hasta=None):
        self.llamadas.append((codigo, desde, hasta))
        payload = {**PAYLOAD_FOOTBALL_DATA, "id": hash(codigo) % 10**6}
        return [_parsear_partido(payload, codigo, "x")]


class TestVentanaEuropa:
    def test_por_defecto_pide_solo_la_ventana_de_fechas(self, db):
        cliente = ClienteEuropaFalso()
        sincronizar_europa(db, cliente)
        assert all(desde and hasta for _, desde, hasta in cliente.llamadas)

    def test_completo_pide_la_temporada_entera(self, db):
        """Sin rango de fechas, football-data.org devuelve la temporada en curso."""
        cliente = ClienteEuropaFalso()
        sincronizar_europa(db, cliente, ventana=False)
        assert cliente.llamadas
        assert all(desde is None and hasta is None for _, desde, hasta in cliente.llamadas)

    def test_cubre_las_cinco_grandes_ligas(self, db):
        cliente = ClienteEuropaFalso()
        sincronizar_europa(db, cliente)
        codigos = {codigo for codigo, _, _ in cliente.llamadas}
        assert {"PL", "PD", "SA", "BL1", "FL1"} <= codigos


class TestSincronizacionSinCredenciales:
    def test_europa_sin_token_no_hace_nada(self, db, monkeypatch):
        """Sin credenciales la app arranca igual: solo se salta la ingesta."""
        from app.servicios.ingesta.football_data import ClienteFootballData

        cliente = ClienteFootballData(token="")
        assert sincronizar_europa(db, cliente) == 0

    def test_paraguay_sin_clave_no_hace_nada(self, db):
        from app.servicios.ingesta.api_football import ClienteApiFootball

        control = ControlCuota(db, Fuente.API_FOOTBALL, 100)
        assert sincronizar_paraguay(db, ClienteApiFootball(control, api_key="")) == 0

    def test_no_se_consume_cuota_si_no_hay_clave(self, db):
        from app.servicios.ingesta.api_football import ClienteApiFootball

        control = ControlCuota(db, Fuente.API_FOOTBALL, 100)
        sincronizar_paraguay(db, ClienteApiFootball(control, api_key=""))
        assert control.restante() == 100
