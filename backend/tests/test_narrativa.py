"""Analisis narrativo escrito por un modelo de lenguaje.

Los tests no llaman a la API: se inyecta un cliente falso. Lo que se fija es el
contrato de nuestro lado — que el contexto lleve lo que la base sabe y declare
lo que no, que un turno pausado por la busqueda web se reanude, y que un fallo
del modelo no rompa la aplicacion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from app.modelos.futbol import Equipo, EstadoPartido, Fuente, Partido, Resultado
from app.modelos.prediccion import NarrativaPartido
from app.servicios import narrativa as servicio
from app.servicios.narrativa import (
    NarrativaNoDisponible,
    construir_contexto,
    generar,
    guardar,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --- Cliente falso ---------------------------------------------------------


@dataclass
class BloqueTexto:
    text: str
    type: str = "text"


@dataclass
class BloqueBusqueda:
    content: object
    type: str = "web_search_tool_result"


@dataclass
class Resultado_:
    url: str


@dataclass
class Uso:
    input_tokens: int = 100
    output_tokens: int = 200


@dataclass
class RespuestaFalsa:
    content: list
    stop_reason: str = "end_turn"
    model: str = "claude-opus-5"
    usage: Uso = field(default_factory=Uso)


class _Flujo:
    def __init__(self, respuesta):
        self._respuesta = respuesta

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self._respuesta


class MensajesFalsos:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.llamadas: list[dict] = []

    def stream(self, **kwargs):
        self.llamadas.append(kwargs)
        return _Flujo(self._respuestas.pop(0))


class ClienteFalso:
    def __init__(self, *respuestas):
        self.messages = MensajesFalsos(respuestas)


# --- Datos ------------------------------------------------------------------


@pytest.fixture
def equipos(db):
    creados = []
    for i, nombre in enumerate(("Alfa", "Beta", "Gamma"), start=1):
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


def _partido(db, local, visitante, dias, goles=(1, 0), programado=False) -> Partido:
    gl, gv = goles
    partido = Partido(
        equipo_local_id=local.id,
        equipo_visitante_id=visitante.id,
        fecha=BASE + timedelta(days=dias),
        liga="Premier League",
        temporada="25/26",
        jornada=5,
        estado=EstadoPartido.PROGRAMADO if programado else EstadoPartido.FINALIZADO,
        goles_local=None if programado else gl,
        goles_visitante=None if programado else gv,
        resultado_real=(
            None
            if programado
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
    return partido


class TestContexto:
    def test_incluye_lo_que_la_base_sabe(self, db, equipos):
        alfa, beta, gamma = equipos
        _partido(db, alfa, beta, -30, goles=(2, 0))
        _partido(db, alfa, gamma, -10, goles=(1, 1))
        actual = _partido(db, alfa, beta, 5, programado=True)

        contexto = construir_contexto(db, actual)

        assert contexto["partido"]["local"] == "Alfa"
        assert contexto["partido"]["competicion"] == "Premier League"
        assert contexto["historial_directo"]["cruces"] == 1
        assert contexto["forma"]["local"]["balance"] == [1, 1, 0]
        assert contexto["rendimiento_por_localia"]["local_jugando_de_local"]["jugados"] == 2

    def test_declara_explicitamente_lo_que_no_sabe(self, db, equipos):
        """El prompt exige aclarar los datos faltantes; el contexto los nombra."""
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)

        faltantes = " ".join(construir_contexto(db, actual)["sin_datos_en_la_base"])
        assert "lesionados" in faltantes
        assert "convocatorias" in faltantes
        assert "tabla" in faltantes

    def test_avisa_que_las_atajadas_son_estimadas(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        assert "estimadas" in construir_contexto(db, actual)["aviso"]

    def test_un_partido_sin_historial_no_explota(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)

        contexto = construir_contexto(db, actual)
        assert contexto["historial_directo"]["cruces"] == 0
        assert contexto["forma"]["local"]["balance"] == [0, 0, 0]


class TestGeneracion:
    def test_devuelve_el_texto_y_el_consumo(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[BloqueTexto("1. CONTEXTO GENERAL\n...")]))

        resultado = generar(db, actual, cliente=cliente)

        assert resultado.texto.startswith("1. CONTEXTO GENERAL")
        assert resultado.modelo == "claude-opus-5"
        assert (resultado.tokens_entrada, resultado.tokens_salida) == (100, 200)

    def test_manda_el_prompt_y_los_datos_medidos(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[BloqueTexto("ok")]))

        generar(db, actual, cliente=cliente)

        bloques = cliente.messages.llamadas[0]["messages"][0]["content"]
        assert "analista deportivo experto" in bloques[0]["text"]
        assert "Alfa vs Beta" in bloques[0]["text"]
        assert "DATOS MEDIDOS" in bloques[1]["text"]

    def test_el_prompt_va_cacheado(self, db, equipos):
        """Es identico en todos los partidos: sin cache se paga entero cada vez."""
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[BloqueTexto("ok")]))

        generar(db, actual, cliente=cliente)

        bloques = cliente.messages.llamadas[0]["messages"][0]["content"]
        assert bloques[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in bloques[1]

    def test_habilita_la_busqueda_web(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[BloqueTexto("ok")]))

        generar(db, actual, cliente=cliente)

        herramientas = cliente.messages.llamadas[0]["tools"]
        assert herramientas[0]["name"] == "web_search"

    def test_recolecta_las_fuentes_citadas(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(
            RespuestaFalsa(
                content=[
                    BloqueBusqueda(
                        content=[Resultado_("https://a.example"), Resultado_("https://b.example")]
                    ),
                    BloqueTexto("analisis"),
                ]
            )
        )

        assert generar(db, actual, cliente=cliente).fuentes == [
            "https://a.example",
            "https://b.example",
        ]

    def test_una_busqueda_fallida_no_rompe_la_narrativa(self, db, equipos):
        """Ante un error la busqueda devuelve un objeto, no una lista de resultados."""
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(
            RespuestaFalsa(
                content=[
                    BloqueBusqueda(content={"error_code": "max_uses_exceeded"}),
                    BloqueTexto("analisis igual"),
                ]
            )
        )

        resultado = generar(db, actual, cliente=cliente)
        assert resultado.fuentes == []
        assert resultado.texto == "analisis igual"

    def test_reanuda_cuando_la_busqueda_pausa_el_turno(self, db, equipos):
        """`pause_turn` sin reanudar devuelve una narrativa cortada sin ningun error."""
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(
            RespuestaFalsa(content=[BloqueTexto("primera parte")], stop_reason="pause_turn"),
            RespuestaFalsa(content=[BloqueTexto("segunda parte")]),
        )

        resultado = generar(db, actual, cliente=cliente)

        assert len(cliente.messages.llamadas) == 2
        assert "primera parte" in resultado.texto
        assert "segunda parte" in resultado.texto
        assert resultado.tokens_salida == 400  # se suman los dos turnos

    def test_una_negativa_del_modelo_se_reporta(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[], stop_reason="refusal"))

        with pytest.raises(NarrativaNoDisponible, match="declino"):
            generar(db, actual, cliente=cliente)

    def test_una_respuesta_sin_texto_se_reporta(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        cliente = ClienteFalso(RespuestaFalsa(content=[]))

        with pytest.raises(NarrativaNoDisponible, match="no devolvio texto"):
            generar(db, actual, cliente=cliente)

    def test_sin_clave_no_se_intenta_llamar(self, db, equipos, monkeypatch):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        monkeypatch.setattr(servicio, "configurado", lambda: False)

        with pytest.raises(NarrativaNoDisponible, match="ANTHROPIC_API_KEY"):
            generar(db, actual)


class TestPersistencia:
    def test_guardar_y_regenerar_no_duplica(self, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)

        for texto in ("primera version", "segunda version"):
            cliente = ClienteFalso(RespuestaFalsa(content=[BloqueTexto(texto)]))
            guardar(db, actual, generar(db, actual, cliente=cliente))
        db.commit()

        assert db.query(NarrativaPartido).count() == 1
        assert db.query(NarrativaPartido).one().texto == "segunda version"


class TestEndpoints:
    def test_sin_narrativa_devuelve_404(self, cliente, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        db.commit()
        assert cliente.get(f"/partidos/{actual.id}/narrativa").status_code == 404

    def test_devuelve_la_narrativa_con_sus_fuentes(self, cliente, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        db.add(
            NarrativaPartido(
                partido_id=actual.id,
                texto="1. CONTEXTO GENERAL...",
                modelo="claude-opus-5",
                fuentes=["https://fuente.example"],
            )
        )
        db.commit()

        cuerpo = cliente.get(f"/partidos/{actual.id}/narrativa").json()
        assert cuerpo["modelo"] == "claude-opus-5"
        assert cuerpo["fuentes"] == ["https://fuente.example"]
        assert "modelo de lenguaje" in cuerpo["aviso"]

    def test_generar_requiere_ser_admin(self, cliente, db, equipos):
        alfa, beta, _ = equipos
        actual = _partido(db, alfa, beta, 5, programado=True)
        db.commit()
        assert cliente.post(f"/admin/narrativa/{actual.id}").status_code == 401
