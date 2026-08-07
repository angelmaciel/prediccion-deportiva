"""Analisis narrativo del partido, escrito por Claude.

El resto del sistema produce numeros; esto produce la lectura en prosa que los
acompania. La division de trabajo es deliberada:

- Lo que la base sabe (historial, forma, estadisticas, veredicto del modelo) se
  le entrega ya calculado. No se le pide al modelo que lo deduzca ni que lo
  recuerde: se lo pasamos medido.
- Lo que la base no sabe (lesiones, sanciones, convocatorias, cambios de DT) es
  justamente donde un modelo sin fuentes inventa. Por eso se habilita la
  busqueda web: puede buscarlo de verdad y citar de donde lo saco.

El prompt exige explicitamente que se aclare cuando un dato no esta confirmado,
en vez de asumirlo. Esa linea es la que separa un analisis de una fabulacion, y
se refuerza en el contexto que se le arma abajo marcando cada bloque sin datos.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.modelos.futbol import Partido
from app.modelos.prediccion import NarrativaPartido
from app.servicios.h2h import (
    con_estadisticas,
    desde_la_optica_de,
    enfrentamientos_previos,
    resumir,
    ultimos_partidos,
)

logger = logging.getLogger(__name__)

# Techo de reintentos cuando la busqueda web agota su ciclo interno y el modelo
# devuelve `pause_turn`. Sin esto la respuesta llega cortada sin ningun error.
MAX_REANUDACIONES = 5

PROMPT = """Actúa como un analista deportivo experto en fútbol, con enfoque táctico, \
estadístico y contextual.
Quiero un análisis completo del partido: {local} vs {visitante}, correspondiente a \
{competicion}, jugado el {fecha}.

Estructura el análisis en los siguientes bloques:

1. CONTEXTO GENERAL
- Competición y qué se juega cada equipo (título, clasificación a copa internacional, \
descenso, etc.)
- Posición actual en la tabla de ambos equipos y diferencia de puntos con rivales directos
- Historial reciente entre ambos (últimos 5 enfrentamientos)

2. ESTADO DE FORMA
- Resultados de los últimos 5-6 partidos de cada equipo (no solo el resultado, también \
cómo lo consiguieron: rendimiento, ocasiones generadas, solidez defensiva)
- Rachas relevantes (invicto, sin ganar, sin marcar, sin recibir goles, etc.)
- Diferencia entre el rendimiento como local y como visitante

3. BAJAS Y ESTADO FÍSICO DEL PLANTEL
- Lesionados confirmados y su importancia en el once titular
- Sancionados o jugadores en la frontera de sanción (acumulación de amarillas)
- Jugadores tocados físicamente o en duda (dudas de última hora)
- Impacto real de cada baja: ¿es un titular indiscutible o un rotativo?

4. CONVOCATORIAS INTERNACIONALES Y ROTACIONES
- Jugadores citados a selecciones nacionales en la fecha FIFA más cercana (antes o \
después del partido)
- Riesgo de que el entrenador rote pensando en un partido de competición internacional \
de clubes (Champions, Libertadores, etc.) cercano
- Posibles suplentes que ganarían minutos por estas ausencias, y su nivel/diferencia \
respecto al titular

5. FACTOR LOCALÍA
- ¿El equipo local realmente saca ventaja de jugar en casa? (porcentaje de puntos como \
local vs visitante)
- Estado de la afición/presión del estadio
- Factores como altitud, clima o superficie de juego si son relevantes

6. FACTORES EXTERNOS (fuera de la estadística pura)
- Cambios recientes de entrenador o crisis interna
- Presión mediática, económica o social sobre el equipo/jugadores
- Fixture congestionado (cuántos días de descanso tuvo cada equipo, viajes largos)
- Motivación extra (derbi, revancha, morbo por ex-jugador o ex-DT)
- Rumores de mercado que puedan afectar la concentración de jugadores clave

7. CONCLUSIÓN Y PRONÓSTICO
- Resumen de los factores que más pueden inclinar la balanza
- Escenario más probable (resultado, tipo de partido: cerrado, abierto, con muchos goles, \
etc.)
- Nivel de confianza del análisis (alto/medio/bajo) según la cantidad de variables \
inciertas (bajas por confirmar, rotaciones, etc.)

Usa datos verificables y actualizados. Si no tienes información confirmada sobre algún \
punto (por ejemplo, una lesión de último momento), acláralo explícitamente en vez de \
asumirlo."""

INSTRUCCIONES = """Los datos medidos del partido van más abajo en JSON: salen de una base \
propia con 30.000 partidos y ya están calculados. Úsalos como fuente para los bloques que \
cubren; no los recalcules ni los contradigas.

Lo que ese JSON no trae — lesiones, sancionados, convocatorias a selección, cambios de \
entrenador, clima, rumores de mercado — no está en la base. Búscalo en la web y cita la \
fuente. Si la búsqueda no lo confirma, escribe explícitamente que no hay información \
confirmada: es preferible un bloque que declara su ignorancia a uno que la disimula.

El bloque 7 debe ser coherente con el veredicto estadístico que viene en el JSON. Si tu \
lectura cualitativa apunta a otro lado, dilo y explica por qué — no lo escondas ni \
reescribas el número."""


class NarrativaNoDisponible(RuntimeError):
    """No hay clave de Anthropic configurada, o el modelo no devolvio texto."""


@dataclass(slots=True)
class ResultadoNarrativa:
    texto: str
    modelo: str
    fuentes: list[str]
    tokens_entrada: int
    tokens_salida: int


def configurado() -> bool:
    return bool(obtener_config().anthropic_api_key)


def _promedios(resumen) -> dict:
    return {
        clave: acumulador.promedio
        for clave, acumulador in resumen.metricas.items()
        if acumulador.promedio is not None
    }


def construir_contexto(db: Session, partido: Partido) -> dict:
    """Arma el JSON con todo lo que la base sabe del partido.

    Los bloques que la base no puede cubrir se listan explicitamente en
    `sin_datos_en_la_base`: es mas seguro decirle al modelo que un dato falta
    que dejar que lo infiera de un silencio.
    """
    h2h = enfrentamientos_previos(db, partido)
    previos_local = ultimos_partidos(db, partido.equipo_local_id, partido.fecha, limite=6)
    previos_visitante = ultimos_partidos(db, partido.equipo_visitante_id, partido.fecha, limite=6)
    solo_local = ultimos_partidos(
        db, partido.equipo_local_id, partido.fecha, localia="local", limite=6
    )
    solo_visitante = ultimos_partidos(
        db, partido.equipo_visitante_id, partido.fecha, localia="visitante", limite=6
    )

    resumen_local = resumir(previos_local, partido.equipo_local_id, partido.equipo_local.nombre)
    resumen_visitante = resumir(
        previos_visitante, partido.equipo_visitante_id, partido.equipo_visitante.nombre
    )
    h2h_local = resumir(h2h, partido.equipo_local_id, partido.equipo_local.nombre)

    contexto: dict = {
        "partido": {
            "local": partido.equipo_local.nombre,
            "visitante": partido.equipo_visitante.nombre,
            "competicion": partido.liga,
            "pais": partido.equipo_local.pais,
            "temporada": partido.temporada,
            "jornada": partido.jornada,
            "fecha_utc": partido.fecha.isoformat(),
        },
        "historial_directo": {
            "cruces": len(h2h),
            "balance_desde_el_local": {
                "ganados": h2h_local.ganados,
                "empatados": h2h_local.empatados,
                "perdidos": h2h_local.perdidos,
            },
            "cruces_con_estadisticas": con_estadisticas(h2h),
            "ultimos": [desde_la_optica_de(p, partido.equipo_local_id) for p in h2h[:5]],
        },
        "forma": {
            "local": {
                "ultimos": [desde_la_optica_de(p, partido.equipo_local_id) for p in previos_local],
                "balance": [resumen_local.ganados, resumen_local.empatados, resumen_local.perdidos],
                "promedios": _promedios(resumen_local),
            },
            "visitante": {
                "ultimos": [
                    desde_la_optica_de(p, partido.equipo_visitante_id) for p in previos_visitante
                ],
                "balance": [
                    resumen_visitante.ganados,
                    resumen_visitante.empatados,
                    resumen_visitante.perdidos,
                ],
                "promedios": _promedios(resumen_visitante),
            },
        },
        "rendimiento_por_localia": {
            "local_jugando_de_local": _balance(solo_local, partido.equipo_local_id),
            "visitante_jugando_de_visitante": _balance(solo_visitante, partido.equipo_visitante_id),
        },
        "sin_datos_en_la_base": [
            "lesionados, sancionados y estado fisico del plantel",
            "convocatorias a selecciones y rotaciones previstas",
            "cambios de entrenador, clima, altitud y rumores de mercado",
            "posiciones en la tabla y puntos con rivales directos",
        ],
        "aviso": (
            "Las estadisticas de remates, corners y tarjetas solo existen para las ligas "
            "europeas importadas de CSV. Las atajadas son estimadas: remates al arco del "
            "rival menos goles recibidos."
        ),
    }

    if partido.features is not None:
        contexto["descanso_dias"] = {
            "local": round(partido.features.dias_descanso_local, 1),
            "visitante": round(partido.features.dias_descanso_visitante, 1),
        }
        contexto["elo"] = {
            "local": round(partido.features.elo_local),
            "visitante": round(partido.features.elo_visitante),
        }

    return contexto


def _balance(previos: list[Partido], equipo_id: int) -> dict:
    """Puntos conseguidos en una condicion concreta (solo local, solo visitante)."""
    if not previos:
        return {"jugados": 0}
    resumen = resumir(previos, equipo_id, "")
    puntos = resumen.ganados * 3 + resumen.empatados
    return {
        "jugados": resumen.jugados,
        "ganados": resumen.ganados,
        "empatados": resumen.empatados,
        "perdidos": resumen.perdidos,
        "puntos_sobre_posibles": f"{puntos}/{resumen.jugados * 3}",
    }


def _herramientas() -> list[dict]:
    if not obtener_config().anthropic_busqueda_web:
        return []
    # Sin esto los bloques 3, 4 y 6 solo pueden decir "no hay datos": es la
    # unica via para hablar de lesiones y convocatorias con una fuente detras.
    return [{"type": "web_search_20260209", "name": "web_search"}]


def _fuentes(contenido) -> list[str]:
    """URLs que la busqueda web devolvio, para poder auditar las afirmaciones."""
    urls: list[str] = []
    for bloque in contenido:
        if getattr(bloque, "type", None) != "web_search_tool_result":
            continue
        resultados = getattr(bloque, "content", None)
        # Ante un error la busqueda devuelve un objeto, no una lista.
        if not isinstance(resultados, list):
            continue
        for resultado in resultados:
            url = getattr(resultado, "url", None)
            if url and url not in urls:
                urls.append(url)
    return urls


def _texto(contenido) -> str:
    partes = [b.text for b in contenido if getattr(b, "type", None) == "text"]
    return "\n\n".join(parte.strip() for parte in partes if parte.strip())


def generar(db: Session, partido: Partido, cliente=None) -> ResultadoNarrativa:
    """Pide el analisis a Claude. `cliente` se inyecta en los tests."""
    config = obtener_config()
    if cliente is None:
        if not configurado():
            raise NarrativaNoDisponible(
                "Falta ANTHROPIC_API_KEY: el analisis narrativo esta desactivado"
            )
        import anthropic

        cliente = anthropic.Anthropic(api_key=config.anthropic_api_key)

    contexto = construir_contexto(db, partido)
    prompt = PROMPT.format(
        local=partido.equipo_local.nombre,
        visitante=partido.equipo_visitante.nombre,
        competicion=partido.liga,
        fecha=partido.fecha.strftime("%d/%m/%Y"),
    )

    datos = json.dumps(contexto, ensure_ascii=False, indent=2)
    mensajes = [
        {
            "role": "user",
            "content": [
                # El prompt es identico en todos los partidos: marcarlo para
                # cache lo cobra a una decima parte a partir del segundo.
                {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": f"{INSTRUCCIONES}\n\nDATOS MEDIDOS:\n{datos}"},
            ],
        }
    ]

    contenido: list = []
    entrada = salida = 0
    for intento in range(MAX_REANUDACIONES + 1):
        with cliente.messages.stream(
            model=config.anthropic_modelo,
            max_tokens=config.anthropic_max_tokens,
            output_config={"effort": config.anthropic_esfuerzo},
            tools=_herramientas(),
            messages=mensajes,
        ) as flujo:
            respuesta = flujo.get_final_message()

        entrada += respuesta.usage.input_tokens
        salida += respuesta.usage.output_tokens
        contenido.extend(respuesta.content)

        if respuesta.stop_reason == "refusal":
            raise NarrativaNoDisponible("El modelo declino responder este pedido")
        if respuesta.stop_reason != "pause_turn":
            break

        # La busqueda web agoto su ciclo interno: se reenvia el turno para que
        # siga desde donde quedo. Sin esto la respuesta llega cortada.
        mensajes.append({"role": "assistant", "content": respuesta.content})
        logger.info("Narrativa del partido %s reanudada (intento %d)", partido.id, intento + 1)
    else:
        logger.warning(
            "Narrativa del partido %s incompleta: se agotaron las reanudaciones", partido.id
        )

    texto = _texto(contenido)
    if not texto:
        raise NarrativaNoDisponible("El modelo no devolvio texto")

    return ResultadoNarrativa(
        texto=texto,
        modelo=respuesta.model,
        fuentes=_fuentes(contenido),
        tokens_entrada=entrada,
        tokens_salida=salida,
    )


def guardar(db: Session, partido: Partido, resultado: ResultadoNarrativa) -> NarrativaPartido:
    """Upsert: un partido tiene una sola narrativa vigente."""
    narrativa = (
        db.query(NarrativaPartido).filter(NarrativaPartido.partido_id == partido.id).one_or_none()
    )
    if narrativa is None:
        narrativa = NarrativaPartido(partido_id=partido.id)
        db.add(narrativa)
    narrativa.texto = resultado.texto
    narrativa.modelo = resultado.modelo
    narrativa.fuentes = resultado.fuentes
    narrativa.tokens_entrada = resultado.tokens_entrada
    narrativa.tokens_salida = resultado.tokens_salida
    narrativa.creado_en = datetime.now(timezone.utc)
    db.flush()
    return narrativa
