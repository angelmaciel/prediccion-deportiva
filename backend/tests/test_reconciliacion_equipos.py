"""Un club es un solo registro, aunque cada fuente lo nombre distinto.

El importador de CSV deja "Arsenal" y football-data.org manda "Arsenal FC". Sin
reconciliar, la base termina con dos equipos: uno con diez temporadas de
historia y otro vacio, y los partidos que vienen apuntan al vacio. Nada falla de
forma visible — el modelo devuelve un tercio para cada resultado y el cara a
cara sale en blanco.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.futbol import Equipo, Fuente
from app.servicios.ingesta.csv_historico import clave_club
from app.servicios.ingesta.football_data import EquipoCrudo
from app.servicios.ingesta.sincronizacion import obtener_o_crear_equipo


def _cargar_csv(db: Session, nombre: str, pais: str = "Inglaterra") -> Equipo:
    """Un equipo tal como lo deja el importador de CSV."""
    equipo = Equipo(
        nombre=nombre,
        liga="Premier League",
        pais=pais,
        fuente=Fuente.CSV_HISTORICO,
        external_id=f"csv-{nombre.lower().replace(' ', '-')}",
    )
    db.add(equipo)
    db.flush()
    return equipo


def _crudo(nombre: str, pais: str = "Inglaterra", externo: str = "api-1") -> EquipoCrudo:
    """Un equipo tal como lo manda football-data.org."""
    return EquipoCrudo(
        external_id=externo,
        nombre=nombre,
        nombre_corto=None,
        liga="Premier League",
        pais=pais,
        escudo_url=None,
    )


@pytest.mark.parametrize(
    ("nombre_csv", "nombre_api", "pais"),
    [
        ("Arsenal", "Arsenal FC", "Inglaterra"),
        ("Chelsea", "Chelsea FC", "Inglaterra"),
        ("Bournemouth", "AFC Bournemouth", "Inglaterra"),
        ("Ajax", "AFC Ajax", "Paises Bajos"),
        # Estos dos solo funcionan si el alias se aplica tambien al nombre ya
        # guardado, no solo al que entra.
        ("Wolves", "Wolverhampton Wanderers FC", "Inglaterra"),
        ("Man United", "Manchester United FC", "Inglaterra"),
    ],
)
def test_la_api_reusa_el_equipo_del_csv(db: Session, nombre_csv, nombre_api, pais):
    existente = _cargar_csv(db, nombre_csv, pais)

    reusado = obtener_o_crear_equipo(db, _crudo(nombre_api, pais), Fuente.FOOTBALL_DATA)

    assert reusado.id == existente.id, f"'{nombre_api}' creo un duplicado de '{nombre_csv}'"
    assert db.execute(select(Equipo)).scalars().all() == [existente]


def test_un_equipo_desconocido_se_crea(db: Session):
    _cargar_csv(db, "Ajax", "Paises Bajos")

    nuevo = obtener_o_crear_equipo(
        db, _crudo("Telstar 1963", "Paises Bajos", "api-2"), Fuente.FOOTBALL_DATA
    )

    assert nuevo.nombre == "Telstar 1963"
    assert len(db.execute(select(Equipo)).scalars().all()) == 2


def test_ante_la_duda_no_fusiona(db: Session):
    """Prefiere un duplicado antes que mezclar dos clubes distintos.

    "RCD Espanyol de Barcelona" contiene la palabra "Barcelona". Unirlo al Barca
    le regalaria una decada de resultados ajenos, y nada lo delataria: los
    numeros seguirian saliendo, solo que mal.
    """
    barca = _cargar_csv(db, "Barcelona", "Espana")

    resuelto = obtener_o_crear_equipo(
        db, _crudo("RCD Espanyol de Barcelona", "Espana", "api-3"), Fuente.FOOTBALL_DATA
    )

    assert resuelto.id != barca.id


def test_el_equipo_reconciliado_conserva_su_historia(db: Session):
    """Adoptar no puede significar empezar de cero: el id se mantiene."""
    existente = _cargar_csv(db, "Arsenal")
    id_original = existente.id

    reusado = obtener_o_crear_equipo(db, _crudo("Arsenal FC"), Fuente.FOOTBALL_DATA)
    db.flush()

    assert reusado.id == id_original
    # Y ahora responde al identificador de la fuente nueva, sin volver a crear.
    otra_vez = obtener_o_crear_equipo(db, _crudo("Arsenal FC"), Fuente.FOOTBALL_DATA)
    assert otra_vez.id == id_original


def test_clave_club_agrupa_los_mismos_y_separa_los_distintos():
    assert clave_club("Arsenal") == clave_club("Arsenal FC")
    assert clave_club("Wolves") == clave_club("Wolverhampton Wanderers FC")
    assert clave_club("Barcelona") != clave_club("RCD Espanyol de Barcelona")
    assert clave_club("Real Madrid") != clave_club("Rayo Vallecano")
