"""Cliente de football-data.org (ligas europeas top).

Plan gratuito: 10 requests/minuto, 12 competiciones, datos con delay. Por eso
solo lo usa el job programado: el frontend nunca golpea esta API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import obtener_config
from app.servicios.ingesta.cuota import LimitadorPorMinuto

logger = logging.getLogger(__name__)

# Competiciones de clubes cubiertas por el plan gratuito. Son la fuente principal
# de la app: es lo unico gratis que llega a la temporada en curso.
COMPETICIONES = {
    "PL": "Premier League",
    "ELC": "Championship",
    "PD": "La Liga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "DED": "Eredivisie",
    "PPL": "Primeira Liga",
    "BSA": "Brasileirao",
    "CL": "Champions League",
}

PAIS_POR_COMPETICION = {
    "PL": "Inglaterra",
    "ELC": "Inglaterra",
    "PD": "Espana",
    "SA": "Italia",
    "BL1": "Alemania",
    "FL1": "Francia",
    "DED": "Paises Bajos",
    "PPL": "Portugal",
    "BSA": "Brasil",
    "CL": "Europa",
}

# football-data.org usa estos estados; los mapeamos a los nuestros.
MAPA_ESTADOS = {
    "SCHEDULED": "programado",
    "TIMED": "programado",
    "IN_PLAY": "en_juego",
    "PAUSED": "en_juego",
    "FINISHED": "finalizado",
    "SUSPENDED": "suspendido",
    "POSTPONED": "suspendido",
    "CANCELLED": "suspendido",
    "AWARDED": "finalizado",
}


@dataclass(slots=True)
class EquipoCrudo:
    external_id: str
    nombre: str
    nombre_corto: str | None
    liga: str
    pais: str
    escudo_url: str | None


@dataclass(slots=True)
class PartidoCrudo:
    external_id: str
    fecha: datetime
    liga: str
    temporada: str | None
    jornada: int | None
    estado: str
    local: EquipoCrudo
    visitante: EquipoCrudo
    goles_local: int | None
    goles_visitante: int | None


class ErrorFuenteExterna(RuntimeError):
    """La API externa fallo o devolvio algo que no podemos interpretar."""


class ClienteFootballData:
    def __init__(self, token: str | None = None, timeout: float = 20.0) -> None:
        config = obtener_config()
        self.token = token if token is not None else config.football_data_token
        self.base = config.football_data_base
        self.timeout = timeout
        self.limitador = LimitadorPorMinuto(config.football_data_rpm)

    @property
    def configurado(self) -> bool:
        return bool(self.token)

    def _get(self, ruta: str, params: dict | None = None) -> dict:
        if not self.configurado:
            raise ErrorFuenteExterna("FOOTBALL_DATA_TOKEN no configurado")
        self.limitador.esperar_turno()
        try:
            respuesta = httpx.get(
                f"{self.base}{ruta}",
                params=params,
                headers={"X-Auth-Token": self.token},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ErrorFuenteExterna(f"Error de red con football-data.org: {exc}") from exc
        if respuesta.status_code == 429:
            raise ErrorFuenteExterna("football-data.org devolvio 429 (rate limit)")
        if respuesta.status_code >= 400:
            raise ErrorFuenteExterna(
                f"football-data.org devolvio {respuesta.status_code} en {ruta}"
            )
        return respuesta.json()

    def partidos_de_competicion(
        self, codigo: str, desde: str | None = None, hasta: str | None = None
    ) -> list[PartidoCrudo]:
        """Trae los partidos de una competicion en un rango de fechas (ISO yyyy-mm-dd)."""
        params: dict[str, str] = {}
        if desde:
            params["dateFrom"] = desde
        if hasta:
            params["dateTo"] = hasta
        datos = self._get(f"/competitions/{codigo}/matches", params or None)
        liga = COMPETICIONES.get(codigo, codigo)
        pais = PAIS_POR_COMPETICION.get(codigo, "Desconocido")
        return [
            crudo
            for item in datos.get("matches", [])
            if (crudo := _parsear_partido(item, liga, pais)) is not None
        ]


def _parsear_partido(item: dict, liga: str, pais: str) -> PartidoCrudo | None:
    """Convierte la respuesta de la API al formato interno; None si es inservible."""
    try:
        local = item["homeTeam"]
        visitante = item["awayTeam"]
        if local.get("id") is None or visitante.get("id") is None:
            # Partidos de fase eliminatoria aun sin equipos definidos.
            return None
        marcador = item.get("score", {}).get("fullTime", {})
        fecha = datetime.fromisoformat(item["utcDate"].replace("Z", "+00:00"))
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        return PartidoCrudo(
            external_id=str(item["id"]),
            fecha=fecha,
            liga=liga,
            temporada=_temporada(item),
            jornada=item.get("matchday"),
            estado=MAPA_ESTADOS.get(item.get("status", ""), "programado"),
            local=_equipo(local, liga, pais),
            visitante=_equipo(visitante, liga, pais),
            goles_local=marcador.get("home"),
            goles_visitante=marcador.get("away"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Partido descartado por formato inesperado: %s", exc)
        return None


def _equipo(datos: dict, liga: str, pais: str) -> EquipoCrudo:
    return EquipoCrudo(
        external_id=str(datos["id"]),
        nombre=datos.get("name") or datos.get("shortName") or f"Equipo {datos['id']}",
        nombre_corto=datos.get("tla") or datos.get("shortName"),
        liga=liga,
        pais=pais,
        escudo_url=datos.get("crest"),
    )


def _temporada(item: dict) -> str | None:
    temporada = item.get("season") or {}
    inicio = temporada.get("startDate")
    fin = temporada.get("endDate")
    if inicio and fin:
        return f"{inicio[:4]}/{fin[:4]}"
    return None
