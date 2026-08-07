"""Historial de enfrentamientos directos.

Lo importante que se prueba: que no se cuele informacion del futuro, que los
filtros de localia y liga hagan lo que dicen, y que un promedio nunca trate un
dato faltante como cero.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.deps import asegurar_utc
from app.modelos.futbol import (
    Equipo,
    EstadisticasPartido,
    EstadoPartido,
    Fuente,
    Partido,
    Resultado,
)
from app.servicios.h2h import (
    con_estadisticas,
    desde_la_optica_de,
    enfrentamientos_previos,
    resumir,
    ultimos_partidos,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def equipos(db):
    creados = []
    for i, nombre in enumerate(("Alfa", "Beta"), start=1):
        equipo = Equipo(
            nombre=nombre,
            liga="Premier League",
            pais="Inglaterra",
            fuente=Fuente.CSV_HISTORICO,
            external_id=f"eq-{i}",
        )
        db.add(equipo)
        creados.append(equipo)
    db.flush()
    return creados


def _partido(
    db,
    local: Equipo,
    visitante: Equipo,
    dias: int,
    goles=(1, 0),
    liga: str = "Premier League",
    estado: EstadoPartido = EstadoPartido.FINALIZADO,
    stats: dict | None = None,
) -> Partido:
    gl, gv = goles
    partido = Partido(
        equipo_local_id=local.id,
        equipo_visitante_id=visitante.id,
        fecha=BASE + timedelta(days=dias),
        liga=liga,
        estado=estado,
        goles_local=gl if estado == EstadoPartido.FINALIZADO else None,
        goles_visitante=gv if estado == EstadoPartido.FINALIZADO else None,
        resultado_real=(
            None
            if estado != EstadoPartido.FINALIZADO
            else Resultado.LOCAL
            if gl > gv
            else Resultado.VISITANTE
            if gl < gv
            else Resultado.EMPATE
        ),
        fuente=Fuente.CSV_HISTORICO,
        external_id=f"p-{local.id}-{visitante.id}-{dias}",
    )
    db.add(partido)
    db.flush()
    if stats:
        db.add(EstadisticasPartido(partido_id=partido.id, **stats))
        db.flush()
    return partido


class TestSeleccionDeCruces:
    def test_no_incluye_partidos_posteriores(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-10)
        _partido(db, alfa, beta, dias=10)  # posterior: no debe aparecer
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        previos = enfrentamientos_previos(db, actual)
        assert len(previos) == 1
        # SQLite devuelve la fecha sin zona; se normaliza antes de comparar.
        assert asegurar_utc(previos[0].fecha) < asegurar_utc(actual.fecha)

    def test_no_se_incluye_a_si_mismo(self, db, equipos):
        alfa, beta = equipos
        actual = _partido(db, alfa, beta, dias=0)
        assert enfrentamientos_previos(db, actual) == []

    def test_toma_los_dos_sentidos_de_la_localia(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20)
        _partido(db, beta, alfa, dias=-10)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        assert len(enfrentamientos_previos(db, actual)) == 2

    def test_filtro_de_localia(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20)
        _partido(db, beta, alfa, dias=-10)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        previos = enfrentamientos_previos(db, actual, solo_misma_localia=True)
        assert len(previos) == 1
        assert previos[0].equipo_local_id == alfa.id

    def test_filtro_de_liga(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20, liga="Premier League")
        _partido(db, alfa, beta, dias=-10, liga="Championship")
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        previos = enfrentamientos_previos(db, actual, liga="Championship")
        assert [p.liga for p in previos] == ["Championship"]

    def test_ignora_los_no_finalizados(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20, estado=EstadoPartido.SUSPENDIDO)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        assert enfrentamientos_previos(db, actual) == []

    def test_ordena_del_mas_reciente_al_mas_viejo(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-30)
        _partido(db, alfa, beta, dias=-5)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        previos = enfrentamientos_previos(db, actual)
        assert previos[0].fecha > previos[1].fecha


class TestResumen:
    def test_cuenta_desde_la_optica_de_cada_equipo(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-30, goles=(2, 0))  # gana Alfa de local
        _partido(db, beta, alfa, dias=-20, goles=(0, 3))  # gana Alfa de visitante
        _partido(db, alfa, beta, dias=-10, goles=(1, 1))  # empate
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)

        resumen_alfa = resumir(previos, alfa.id, "Alfa")
        assert (resumen_alfa.ganados, resumen_alfa.empatados, resumen_alfa.perdidos) == (2, 1, 0)
        assert resumen_alfa.metricas["goles_favor"].promedio == 2.0

        resumen_beta = resumir(previos, beta.id, "Beta")
        assert (resumen_beta.ganados, resumen_beta.empatados, resumen_beta.perdidos) == (0, 1, 2)
        assert resumen_beta.metricas["goles_contra"].promedio == 2.0

    def test_promedia_las_estadisticas_por_lado(self, db, equipos):
        alfa, beta = equipos
        _partido(
            db,
            alfa,
            beta,
            dias=-20,
            goles=(1, 0),
            stats={"corners_local": 8, "corners_visitante": 2},
        )
        _partido(
            db,
            beta,
            alfa,
            dias=-10,
            goles=(0, 0),
            stats={"corners_local": 4, "corners_visitante": 6},
        )
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)

        # Alfa: 8 de local y 6 de visitante -> 7.0
        assert resumir(previos, alfa.id, "Alfa").metricas["corners"].promedio == 7.0
        assert resumir(previos, beta.id, "Beta").metricas["corners"].promedio == 3.0

    def test_un_dato_faltante_no_cuenta_como_cero(self, db, equipos):
        """Lo que arruinaria el promedio: dividir por partidos sin estadisticas."""
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20, stats={"corners_local": 10, "corners_visitante": 1})
        _partido(db, alfa, beta, dias=-10)  # sin estadisticas
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)

        resumen = resumir(previos, alfa.id, "Alfa")
        assert resumen.jugados == 2
        assert resumen.metricas["corners"].promedio == 10.0  # no 5.0
        assert con_estadisticas(previos) == 1

    def test_sin_ningun_dato_el_promedio_es_nulo(self, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-10)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)
        assert resumir(previos, alfa.id, "Alfa").metricas["corners"].promedio is None

    def test_atajadas_estimadas(self, db, equipos):
        """Atajadas del local = remates al arco del visitante que no fueron gol."""
        alfa, beta = equipos
        _partido(
            db,
            alfa,
            beta,
            dias=-10,
            goles=(1, 2),
            stats={"remates_arco_local": 7, "remates_arco_visitante": 5},
        )
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)

        assert resumir(previos, alfa.id, "Alfa").metricas["atajadas"].promedio == 3.0  # 5 - 2
        assert resumir(previos, beta.id, "Beta").metricas["atajadas"].promedio == 6.0  # 7 - 1

    def test_las_atajadas_nunca_son_negativas(self, db, equipos):
        """Si hay mas goles que remates al arco registrados, el minimo es cero."""
        alfa, beta = equipos
        _partido(
            db,
            alfa,
            beta,
            dias=-10,
            goles=(0, 4),
            stats={"remates_arco_local": 1, "remates_arco_visitante": 2},
        )
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)
        previos = enfrentamientos_previos(db, actual)
        assert resumir(previos, alfa.id, "Alfa").metricas["atajadas"].promedio == 0.0


class TestRachaReciente:
    """Ultimos partidos de un equipo contra cualquier rival, no solo contra este."""

    @pytest.fixture
    def tercero(self, db):
        equipo = Equipo(
            nombre="Gamma",
            liga="Premier League",
            pais="Inglaterra",
            fuente=Fuente.CSV_HISTORICO,
            external_id="eq-3",
        )
        db.add(equipo)
        db.flush()
        return equipo

    def test_incluye_partidos_contra_otros_rivales(self, db, equipos, tercero):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20)
        _partido(db, alfa, tercero, dias=-10)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        previos = ultimos_partidos(db, alfa.id, actual.fecha)
        assert len(previos) == 2

    def test_filtra_por_localia(self, db, equipos, tercero):
        alfa, beta = equipos
        _partido(db, alfa, tercero, dias=-20)  # Alfa de local
        _partido(db, tercero, alfa, dias=-10)  # Alfa de visitante
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        de_local = ultimos_partidos(db, alfa.id, actual.fecha, localia="local")
        de_visitante = ultimos_partidos(db, alfa.id, actual.fecha, localia="visitante")
        assert len(de_local) == 1
        assert de_local[0].equipo_local_id == alfa.id
        assert len(de_visitante) == 1
        assert de_visitante[0].equipo_visitante_id == alfa.id

    def test_respeta_el_limite(self, db, equipos, tercero):
        alfa, beta = equipos
        for dia in range(1, 8):
            _partido(db, alfa, tercero, dias=-dia)
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        assert len(ultimos_partidos(db, alfa.id, actual.fecha, limite=3)) == 3

    def test_optica_del_equipo(self, db, equipos, tercero):
        """Un 0-2 de visitante es una derrota, no un 'goles_local 0'."""
        alfa, beta = equipos
        _partido(db, tercero, alfa, dias=-10, goles=(0, 2))
        actual = _partido(db, alfa, beta, dias=0, estado=EstadoPartido.PROGRAMADO)

        vista = desde_la_optica_de(ultimos_partidos(db, alfa.id, actual.fecha)[0], alfa.id)
        assert vista["rival"] == "Gamma"
        assert vista["de_local"] is False
        assert (vista["goles_favor"], vista["goles_contra"]) == (2, 0)
        assert vista["resultado"] == "G"

    def test_el_endpoint_devuelve_las_dos_rachas(self, cliente, db, equipos, tercero):
        alfa, beta = equipos
        _partido(db, alfa, tercero, dias=-20, goles=(3, 0))
        _partido(db, tercero, beta, dias=-15, goles=(2, 1))
        actual = _partido(db, alfa, beta, dias=5, estado=EstadoPartido.PROGRAMADO)
        db.commit()

        cuerpo = cliente.get(f"/partidos/{actual.id}/h2h").json()
        assert cuerpo["racha_local"]["nombre"] == "Alfa"
        assert cuerpo["racha_local"]["ganados"] == 1
        assert cuerpo["racha_local"]["partidos"][0]["rival"] == "Gamma"
        assert cuerpo["racha_visitante"]["nombre"] == "Beta"
        assert cuerpo["racha_visitante"]["perdidos"] == 1
        assert cuerpo["racha_visitante"]["partidos"][0]["resultado"] == "P"

    def test_el_filtro_de_localia_mira_a_cada_equipo_en_su_condicion(
        self, cliente, db, equipos, tercero
    ):
        """Con el filtro puesto: el local solo de local, el visitante solo de visitante."""
        alfa, beta = equipos
        _partido(db, alfa, tercero, dias=-20)  # Alfa de local: cuenta
        _partido(db, tercero, alfa, dias=-19)  # Alfa de visitante: no cuenta
        _partido(db, tercero, beta, dias=-18)  # Beta de visitante: cuenta
        _partido(db, beta, tercero, dias=-17)  # Beta de local: no cuenta
        actual = _partido(db, alfa, beta, dias=5, estado=EstadoPartido.PROGRAMADO)
        db.commit()

        cuerpo = cliente.get(f"/partidos/{actual.id}/h2h?solo_misma_localia=true").json()
        assert cuerpo["racha_local"]["jugados"] == 1
        assert cuerpo["racha_local"]["partidos"][0]["de_local"] is True
        assert cuerpo["racha_visitante"]["jugados"] == 1
        assert cuerpo["racha_visitante"]["partidos"][0]["de_local"] is False


class TestEndpoint:
    def test_devuelve_el_historial_completo(self, cliente, db, equipos):
        alfa, beta = equipos
        _partido(
            db,
            alfa,
            beta,
            dias=-20,
            goles=(2, 1),
            stats={"corners_local": 6, "corners_visitante": 3, "remates_local": 14},
        )
        actual = _partido(db, alfa, beta, dias=5, estado=EstadoPartido.PROGRAMADO)
        db.commit()

        cuerpo = cliente.get(f"/partidos/{actual.id}/h2h").json()
        assert cuerpo["total_cruces"] == 1
        assert cuerpo["cruces_con_estadisticas"] == 1
        assert cuerpo["local"]["nombre"] == "Alfa"
        assert cuerpo["local"]["ganados"] == 1
        assert cuerpo["local"]["promedios"]["corners"] == 6.0
        assert cuerpo["visitante"]["promedios"]["remates"] is None
        assert "estimacion" in cuerpo["aviso_atajadas"]

    def test_filtros_por_query(self, cliente, db, equipos):
        alfa, beta = equipos
        _partido(db, alfa, beta, dias=-20)
        _partido(db, beta, alfa, dias=-10)
        actual = _partido(db, alfa, beta, dias=5, estado=EstadoPartido.PROGRAMADO)
        db.commit()

        completo = cliente.get(f"/partidos/{actual.id}/h2h").json()
        filtrado = cliente.get(f"/partidos/{actual.id}/h2h?solo_misma_localia=true").json()
        assert completo["total_cruces"] == 2
        assert filtrado["total_cruces"] == 1
        assert filtrado["solo_misma_localia"] is True

    def test_partido_inexistente(self, cliente):
        assert cliente.get("/partidos/999999/h2h").status_code == 404

    def test_sin_historial_devuelve_vacio_no_error(self, cliente, db, equipos):
        alfa, beta = equipos
        actual = _partido(db, alfa, beta, dias=5, estado=EstadoPartido.PROGRAMADO)
        db.commit()

        cuerpo = cliente.get(f"/partidos/{actual.id}/h2h").json()
        assert cuerpo["total_cruces"] == 0
        assert cuerpo["local"]["jugados"] == 0
        assert cuerpo["local"]["promedios"]["goles_favor"] is None
