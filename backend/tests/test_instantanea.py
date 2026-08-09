"""La instantanea que el sitio estatico sirve desde el CDN.

Lo que se fija aca es que el archivo tenga la misma forma que la API. Si
divergen, la portada pinta con el respaldo y despues cambia de layout cuando
llega la respuesta real, que es peor que no tener respaldo.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.servicios.instantanea import construir_instantanea
from tests.conftest import crear_partido


def _dias(n: int) -> datetime:
    ahora = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    return ahora + timedelta(days=n)


@pytest.fixture
def sembrado(db, equipos):
    return {
        "viejo": crear_partido(db, equipos[0], equipos[1], _dias(-40), 2, 0, externo="i-viejo"),
        "ayer": crear_partido(db, equipos[2], equipos[3], _dias(-1), 1, 1, externo="i-ayer"),
        "manana": crear_partido(db, equipos[4], equipos[5], _dias(1), externo="i-manana"),
    }


class TestInstantanea:
    def test_separa_programados_de_finalizados(self, db, sembrado):
        datos = construir_instantanea(db)
        assert [p["id"] for p in datos["proximos"]] == [sembrado["manana"].id]
        assert [p["id"] for p in datos["resultados"]] == [sembrado["ayer"].id]

    def test_deja_afuera_lo_viejo(self, db, sembrado):
        datos = construir_instantanea(db)
        ids = {p["id"] for p in datos["proximos"] + datos["resultados"]}
        assert sembrado["viejo"].id not in ids

    def test_la_ventana_es_mas_ancha_que_la_de_la_api(self, db, equipos):
        """Se genera una vez al dia pero se lee todo el dia: sin margen, caduca."""
        pasado_manana = crear_partido(db, equipos[0], equipos[1], _dias(2), externo="i-lejos")
        datos = construir_instantanea(db)
        assert pasado_manana.id in {p["id"] for p in datos["proximos"]}

    def test_trae_la_prediccion_igual_que_la_api(self, cliente, db, sembrado):
        """Mismo partido, misma forma: la portada no puede notar la diferencia."""
        desde_la_api = cliente.get("/partidos/proximos").json()
        desde_el_archivo = construir_instantanea(db)["proximos"]

        por_id = {p["id"]: p for p in desde_el_archivo}
        assert desde_la_api, "el sembrado tiene que dejar al menos un programado"
        for partido in desde_la_api:
            assert por_id[partido["id"]] == partido

    def test_es_json_serializable(self, db, sembrado):
        """Se escribe a un archivo: un datetime suelto reventaria recien ahi."""
        texto = json.dumps(construir_instantanea(db), ensure_ascii=False)
        assert json.loads(texto)["generado_en"]

    def test_sin_partidos_no_falla(self, db):
        datos = construir_instantanea(db)
        assert datos["proximos"] == []
        assert datos["resultados"] == []
        assert datos["ligas"] == []
