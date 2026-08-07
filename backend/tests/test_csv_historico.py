"""Importador del historico de football-data.co.uk.

El foco esta en la reconciliacion de nombres: un falso positivo le asigna a un
club los resultados de otro y envenena el modelo en silencio.
"""

from __future__ import annotations

from datetime import timezone

import pytest

from app.modelos.futbol import Equipo, EstadoPartido, Fuente, Partido, Resultado
from app.servicios.ingesta.csv_historico import (
    _external_id,
    _indice_equipos,
    _resolver,
    _sobrantes,
    importar_division,
    normalizar,
    parsear,
    temporadas_recientes,
    url_temporada,
)

CSV_MINIMO = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
    "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H\n"
    "E0,16/08/2025,12:30,Aston Villa,Newcastle,0,0,D\n"
    "E0,17/08/2025,15:00,Man United,Arsenal,0,1,A\n"
)


def _equipo(db, nombre: str, pais: str = "Inglaterra") -> Equipo:
    equipo = Equipo(
        nombre=nombre,
        liga="Premier League",
        pais=pais,
        fuente=Fuente.FOOTBALL_DATA,
        external_id=f"fd-{nombre}",
    )
    db.add(equipo)
    db.flush()
    return equipo


class TestNormalizacion:
    @pytest.mark.parametrize(
        "crudo,esperado",
        [
            ("1. FC Köln", "koln"),
            ("FC Bayern München", "bayern munchen"),
            ("Sport Lisboa e Benfica", "sport lisboa benfica"),
            ("Como 1907", "como"),
            ("Brighton & Hove Albion FC", "brighton hove albion"),
        ],
    )
    def test_reduce_al_nucleo_del_nombre(self, crudo, esperado):
        assert normalizar(crudo) == esperado


class TestSobrantes:
    def test_cuenta_las_palabras_de_mas(self):
        assert _sobrantes(["angers"], ["angers", "sco"]) == 1

    def test_sin_contencion_devuelve_none(self):
        assert _sobrantes(["real", "madrid"], ["rayo", "vallecano", "madrid"]) is None

    def test_tolera_variantes_ortograficas(self):
        assert _sobrantes(["inter", "milan"], ["inter", "milano"]) == 0

    def test_las_diferencias_grandes_necesitan_alias(self):
        """ "Munich" y "Munchen" no se parecen lo suficiente: van por ALIAS_CRUDO."""
        assert _sobrantes(["bayern", "munich"], ["bayern", "munchen"]) is None


class TestResolucionDeNombres:
    def test_prefiere_el_nombre_con_menos_palabras_de_sobra(self, db):
        """El caso que motiva todo: 'Barcelona' no puede caer en el Espanyol."""
        barsa = _equipo(db, "FC Barcelona", "Espana")
        _equipo(db, "RCD Espanyol de Barcelona", "Espana")

        equipo, _ = _resolver("Barcelona", _indice_equipos(db, "Espana"))
        assert equipo is barsa

    def test_no_confunde_clubes_de_la_misma_ciudad(self, db):
        _equipo(db, "Rayo Vallecano de Madrid", "Espana")
        equipo, _ = _resolver("Real Madrid", _indice_equipos(db, "Espana"))
        assert equipo is None

    def test_empate_no_resuelve(self, db):
        """Dos candidatos igual de plausibles: mejor crear equipo que adivinar."""
        _equipo(db, "Sporting Clube de Braga", "Portugal")
        _equipo(db, "Sporting Clube de Portugal", "Portugal")

        equipo, _ = _resolver("Sporting", _indice_equipos(db, "Portugal"))
        assert equipo is None

    def test_resuelve_abreviaturas_por_alias(self, db):
        united = _equipo(db, "Manchester United FC")
        equipo, _ = _resolver("Man United", _indice_equipos(db, "Inglaterra"))
        assert equipo is united

    def test_acepta_nombre_oficial_mas_largo(self, db):
        lens = _equipo(db, "Racing Club de Lens", "Francia")
        equipo, _ = _resolver("Lens", _indice_equipos(db, "Francia"))
        assert equipo is lens

    def test_no_cruza_paises(self, db):
        _equipo(db, "Valencia CF", "Espana")
        assert _resolver("Valencia", _indice_equipos(db, "Italia"))[0] is None


class TestParseo:
    def test_lee_las_columnas_que_importan(self):
        filas = parsear(CSV_MINIMO)
        assert len(filas) == 3
        assert filas[0].local == "Liverpool"
        assert (filas[0].goles_local, filas[0].goles_visitante) == (4, 2)
        assert filas[0].fecha.tzinfo == timezone.utc
        assert filas[0].fecha.hour == 20

    def test_acepta_anio_de_dos_digitos(self):
        filas = parsear("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,15/08/25,A,B,1,0\n")
        assert filas[0].fecha.year == 2025

    def test_descarta_filas_sin_resultado(self):
        crudo = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,15/08/2025,A,B,,\nE0,,,,,\n"
        assert parsear(crudo) == []


class TestIdentidadDePartidos:
    def test_el_id_es_estable(self):
        filas = parsear(CSV_MINIMO)
        assert _external_id("E0", filas[0]) == _external_id("E0", filas[0])

    def test_partidos_distintos_no_colisionan(self):
        filas = parsear(CSV_MINIMO)
        ids = {_external_id("E0", f) for f in filas}
        assert len(ids) == len(filas)

    def test_entra_en_la_columna(self):
        assert len(_external_id("SP1", parsear(CSV_MINIMO)[0])) <= 40


class TestImportacion:
    def test_importa_y_reconcilia_contra_los_equipos_existentes(self, db, monkeypatch):
        liverpool = _equipo(db, "Liverpool FC")
        _equipo(db, "Manchester United FC")
        _equipo(db, "Arsenal FC")
        db.commit()

        monkeypatch.setattr(
            "app.servicios.ingesta.csv_historico.descargar",
            lambda division, temporada, timeout=60.0: CSV_MINIMO,
        )
        resultado = importar_division(db, "E0", "2526")
        db.commit()

        assert resultado.partidos_nuevos == 3
        partido = db.query(Partido).filter(Partido.equipo_local_id == liverpool.id).one()
        assert partido.estado == EstadoPartido.FINALIZADO
        assert partido.resultado_real == Resultado.LOCAL
        assert partido.fuente == Fuente.CSV_HISTORICO
        assert partido.temporada == "25/26"

    def test_reimportar_no_duplica(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.servicios.ingesta.csv_historico.descargar",
            lambda division, temporada, timeout=60.0: CSV_MINIMO,
        )
        importar_division(db, "E0", "2526")
        db.commit()
        segunda = importar_division(db, "E0", "2526")
        db.commit()

        assert segunda.partidos_nuevos == 0
        assert segunda.partidos_actualizados == 3
        assert db.query(Partido).count() == 3

    def test_los_equipos_desconocidos_se_crean_y_se_reportan(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.servicios.ingesta.csv_historico.descargar",
            lambda division, temporada, timeout=60.0: CSV_MINIMO,
        )
        resultado = importar_division(db, "E0", "2526")
        db.commit()

        assert len(resultado.equipos_creados) == 6
        assert db.query(Equipo).filter(Equipo.fuente == Fuente.CSV_HISTORICO).count() == 6


class TestTemporadas:
    def test_codigos_del_sitio(self):
        assert temporadas_recientes(3, hasta=2026) == ["2324", "2425", "2526"]

    def test_url(self):
        assert url_temporada("E0", "2526").endswith("/mmz4281/2526/E0.csv")
