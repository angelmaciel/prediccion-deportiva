"""Cliente de API-Football (API-Sports) para la Primera Division de Paraguay.

El plan gratuito da 100 requests por dia, asi que este cliente se trata como
fuente de actualizacion periodica (1-2 veces al dia), nunca como consulta en
vivo por usuario. Cada llamada pasa por `ControlCuota`, que corta antes de que
la API nos bloquee.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.core.config import obtener_config
from app.servicios.ingesta.cuota import ControlCuota
from app.servicios.ingesta.football_data import (
    EquipoCrudo,
    ErrorFuenteExterna,
    PartidoCrudo,
)

logger = logging.getLogger(__name__)

# ID de la Primera Division de Paraguay en API-Football.
LIGA_PARAGUAY_ID = 250
LIGA_PARAGUAY_NOMBRE = "Primera Division de Paraguay"

MAPA_ESTADOS = {
    "TBD": "programado",
    "NS": "programado",
    "1H": "en_juego",
    "HT": "en_juego",
    "2H": "en_juego",
    "ET": "en_juego",
    "BT": "en_juego",
    "P": "en_juego",
    "LIVE": "en_juego",
    "FT": "finalizado",
    "AET": "finalizado",
    "PEN": "finalizado",
    "SUSP": "suspendido",
    "INT": "suspendido",
    "PST": "suspendido",
    "CANC": "suspendido",
    "ABD": "suspendido",
    "AWD": "finalizado",
    "WO": "finalizado",
}


class ClienteApiFootball:
    def __init__(self, control_cuota: ControlCuota, api_key: str | None = None) -> None:
        config = obtener_config()
        self.api_key = api_key if api_key is not None else config.api_football_key
        self.host = config.api_football_host
        self.control = control_cuota
        self.timeout = 20.0

    @property
    def configurado(self) -> bool:
        return bool(self.api_key)

    def _get(self, ruta: str, params: dict) -> dict:
        if not self.configurado:
            raise ErrorFuenteExterna("API_FOOTBALL_KEY no configurada")
        self.control.verificar(1)
        try:
            respuesta = httpx.get(
                f"https://{self.host}{ruta}",
                params=params,
                headers={"x-apisports-key": self.api_key, "x-apisports-host": self.host},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            self.control.consumir(1, error=True)
            raise ErrorFuenteExterna(f"Error de red con API-Football: {exc}") from exc

        self.control.consumir(1, error=respuesta.status_code >= 400)
        if respuesta.status_code == 429:
            raise ErrorFuenteExterna("API-Football devolvio 429 (cuota agotada)")
        if respuesta.status_code >= 400:
            raise ErrorFuenteExterna(f"API-Football devolvio {respuesta.status_code} en {ruta}")

        datos = respuesta.json()
        # La API responde 200 con `errors` poblado cuando la clave es invalida
        # o se supero el plan; hay que mirarlo explicitamente.
        errores = datos.get("errors")
        if errores and (not isinstance(errores, list) or len(errores) > 0):
            raise ErrorFuenteExterna(f"API-Football reporto errores: {errores}")
        return datos

    def partidos_temporada(
        self, temporada: int, liga_id: int = LIGA_PARAGUAY_ID
    ) -> list[PartidoCrudo]:
        """Trae la temporada completa en un solo request (economico en cuota)."""
        datos = self._get("/fixtures", {"league": liga_id, "season": temporada})
        crudos = []
        for item in datos.get("response", []):
            parseado = _parsear_fixture(item, temporada)
            if parseado is not None:
                crudos.append(parseado)
        return crudos


def _parsear_fixture(item: dict, temporada: int) -> PartidoCrudo | None:
    try:
        fixture = item["fixture"]
        equipos = item["teams"]
        goles = item.get("goals", {})
        liga = item.get("league", {})
        nombre_liga = liga.get("name") or LIGA_PARAGUAY_NOMBRE
        pais = liga.get("country") or "Paraguay"

        fecha = datetime.fromisoformat(fixture["date"].replace("Z", "+00:00"))
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        return PartidoCrudo(
            external_id=str(fixture["id"]),
            fecha=fecha,
            liga=nombre_liga,
            temporada=str(temporada),
            jornada=_jornada(liga.get("round")),
            estado=MAPA_ESTADOS.get(fixture.get("status", {}).get("short", ""), "programado"),
            local=_equipo(equipos["home"], nombre_liga, pais),
            visitante=_equipo(equipos["away"], nombre_liga, pais),
            goles_local=goles.get("home"),
            goles_visitante=goles.get("away"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Fixture descartado por formato inesperado: %s", exc)
        return None


def _equipo(datos: dict, liga: str, pais: str) -> EquipoCrudo:
    return EquipoCrudo(
        external_id=str(datos["id"]),
        nombre=datos["name"],
        nombre_corto=None,
        liga=liga,
        pais=pais,
        escudo_url=datos.get("logo"),
    )


def _jornada(ronda: str | None) -> int | None:
    """Extrae el numero de 'Regular Season - 12'."""
    if not ronda:
        return None
    for parte in reversed(ronda.replace("-", " ").split()):
        if parte.isdigit():
            return int(parte)
    return None
