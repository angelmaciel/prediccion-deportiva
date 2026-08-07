"""Punto de extension para analisis propios.

Lo que se fija aca es el contrato con quien escribe un analizador: que datos
recibe, que pasa si su regla explota, y que un dato faltante nunca se cuente
como cero.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ml import personalizado
from app.ml.personalizado import (
    ContextoPartido,
    LadoPartido,
    Senial,
    evaluar,
    registrar,
)
from app.modelos.futbol import (
    EstadisticasPartido,
    EstadoPartido,
    Fuente,
    Partido,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def analizadores_limpios(monkeypatch):
    """Aisla el registro: un test no puede ver los analizadores de otro."""
    monkeypatch.setattr(personalizado, "ANALIZADORES", [])
    return personalizado.ANALIZADORES


def _partido(local_id: int, visitante_id: int, dias: int, goles=(1, 0), stats=None) -> Partido:
    partido = Partido(
        id=abs(hash((local_id, visitante_id, dias))) % 100000,
        equipo_local_id=local_id,
        equipo_visitante_id=visitante_id,
        fecha=BASE + timedelta(days=dias),
        liga="Premier League",
        estado=EstadoPartido.FINALIZADO,
        goles_local=goles[0],
        goles_visitante=goles[1],
        fuente=Fuente.CSV_HISTORICO,
        external_id=f"x-{local_id}-{visitante_id}-{dias}",
    )
    partido.estadisticas = EstadisticasPartido(**stats) if stats else None
    return partido


def _contexto(previos_local=(), previos_visitante=(), h2h=()) -> ContextoPartido:
    return ContextoPartido(
        partido=_partido(1, 2, 0),
        local=LadoPartido(equipo_id=1, nombre="Alfa", de_local=True, previos=list(previos_local)),
        visitante=LadoPartido(
            equipo_id=2, nombre="Beta", de_local=False, previos=list(previos_visitante)
        ),
        h2h=list(h2h),
    )


class TestLadoPartido:
    def test_los_goles_se_leen_desde_la_optica_del_equipo(self):
        lado = LadoPartido(
            equipo_id=1,
            nombre="Alfa",
            de_local=True,
            previos=[
                _partido(1, 9, -10, goles=(3, 1)),  # de local: 3 a favor
                _partido(9, 1, -20, goles=(0, 2)),  # de visitante: 2 a favor
            ],
        )
        assert lado.goles_favor() == [3, 2]
        assert lado.goles_contra() == [1, 0]

    def test_la_estadistica_se_lee_del_lado_correcto(self):
        lado = LadoPartido(
            equipo_id=1,
            nombre="Alfa",
            de_local=True,
            previos=[
                _partido(1, 9, -10, stats={"corners_local": 9, "corners_visitante": 2}),
                _partido(9, 1, -20, stats={"corners_local": 3, "corners_visitante": 7}),
            ],
        )
        assert lado.estadistica("corners") == [9, 7]
        assert lado.promedio("corners") == 8.0

    def test_un_partido_sin_estadisticas_no_cuenta_como_cero(self):
        lado = LadoPartido(
            equipo_id=1,
            nombre="Alfa",
            de_local=True,
            previos=[
                _partido(1, 9, -10, stats={"corners_local": 10, "corners_visitante": 1}),
                _partido(1, 9, -20),  # sin estadisticas
            ],
        )
        assert lado.promedio("corners") == 10.0  # no 5.0

    def test_sin_ningun_dato_el_promedio_es_nulo(self):
        lado = LadoPartido(equipo_id=1, nombre="Alfa", de_local=True, previos=[])
        assert lado.promedio("corners") is None

    def test_puntos_recientes_respeta_la_ventana(self):
        lado = LadoPartido(
            equipo_id=1,
            nombre="Alfa",
            de_local=True,
            previos=[
                _partido(1, 9, -10, goles=(2, 0)),  # ganado
                _partido(1, 9, -20, goles=(1, 1)),  # empatado
                _partido(1, 9, -30, goles=(0, 3)),  # perdido
            ],
        )
        assert lado.puntos_recientes(ventana=2) == 4
        assert lado.puntos_recientes() == 4


class TestRegistro:
    def test_un_analizador_registrado_se_ejecuta(self, analizadores_limpios):
        @registrar
        def siempre(_contexto):
            return Senial("Propio", "siempre dice algo", favorece="L")

        seniales = evaluar(_contexto())
        assert [s.nombre for s in seniales] == ["Propio"]

    def test_devolver_none_es_no_opinar(self, analizadores_limpios):
        @registrar
        def callado(_contexto):
            return None

        assert evaluar(_contexto()) == []

    def test_un_analizador_roto_no_tumba_el_veredicto(self, analizadores_limpios, caplog):
        @registrar
        def roto(_contexto):
            raise ValueError("me equivoque en la cuenta")

        @registrar
        def sano(_contexto):
            return Senial("Sano", "sigue funcionando")

        seniales = evaluar(_contexto())
        assert [s.nombre for s in seniales] == ["Sano"]
        assert "roto" in caplog.text  # el fallo queda registrado, no en silencio

    def test_se_ordenan_por_peso(self, analizadores_limpios):
        @registrar
        def flojo(_contexto):
            return Senial("Flojo", "poco importante", peso=0.2)

        @registrar
        def fuerte(_contexto):
            return Senial("Fuerte", "muy importante", peso=0.9)

        assert [s.nombre for s in evaluar(_contexto())] == ["Fuerte", "Flojo"]


class TestEjemplos:
    """Los analizadores de ejemplo que vienen en el modulo."""

    def test_presion_ofensiva_detecta_la_diferencia(self):
        contexto = _contexto(
            previos_local=[
                _partido(1, 9, -d, stats={"remates_arco_local": 8, "remates_arco_visitante": 2})
                for d in (10, 20, 30)
            ],
            previos_visitante=[
                _partido(2, 9, -d, stats={"remates_arco_local": 2, "remates_arco_visitante": 1})
                for d in (10, 20, 30)
            ],
        )
        senial = personalizado.presion_ofensiva(contexto)
        assert senial is not None
        assert senial.favorece == "L"

    def test_presion_ofensiva_calla_si_estan_parejos(self):
        iguales = [
            _partido(1, 9, -d, stats={"remates_arco_local": 4, "remates_arco_visitante": 4})
            for d in (10, 20, 30)
        ]
        contexto = _contexto(previos_local=iguales, previos_visitante=iguales)
        assert personalizado.presion_ofensiva(contexto) is None

    def test_presion_ofensiva_calla_sin_estadisticas(self):
        contexto = _contexto(
            previos_local=[_partido(1, 9, -10)], previos_visitante=[_partido(2, 9, -10)]
        )
        assert personalizado.presion_ofensiva(contexto) is None

    def test_dominio_historico_necesita_muestra(self):
        pocos = [_partido(1, 2, -d, goles=(2, 0)) for d in (10, 20)]
        assert personalizado.dominio_historico(_contexto(h2h=pocos)) is None

    def test_dominio_historico_detecta_una_racha_clara(self):
        cruces = [_partido(1, 2, -d, goles=(2, 0)) for d in (10, 20, 30, 40)]
        senial = personalizado.dominio_historico(_contexto(h2h=cruces))
        assert senial is not None
        assert senial.favorece == "L"
        assert "4 de 4" in senial.detalle

    def test_dominio_historico_calla_si_esta_repartido(self):
        cruces = [
            _partido(1, 2, -10, goles=(2, 0)),
            _partido(1, 2, -20, goles=(0, 2)),
            _partido(2, 1, -30, goles=(1, 0)),
            _partido(2, 1, -40, goles=(0, 1)),
        ]
        assert personalizado.dominio_historico(_contexto(h2h=cruces)) is None
