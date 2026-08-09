"""Ventana de fechas por defecto para los listados publicos.

Las tres secciones que ve un visitante (proximos partidos, resultados e
historial de aciertos) muestran por defecto solo ayer, hoy y manana. La base
guarda temporadas enteras, y traerlas siempre entera es lo que hacia lenta la
carga inicial: el 99 % de las visitas mira los partidos de la fecha.

El historico completo sigue disponible, pero hay que pedirlo explicitamente
(`historico=true` o un rango `desde`/`hasta`), asi el costo lo paga solo quien
lo consulta.

Los cortes son en la zona del publico, no en UTC. La diferencia no es cosmetica:
en Asuncion (UTC-3) un partido de las 21:00 cae al dia siguiente en UTC, asi que
una ventana calculada en UTC dejaba afuera justo los partidos de la noche, que
son los que mas se miran.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import obtener_config

logger = logging.getLogger(__name__)

# Dias hacia atras y hacia adelante alrededor de hoy.
DIAS_VENTANA = 1


@lru_cache(maxsize=4)
def _zona(nombre: str) -> ZoneInfo:
    """Resuelve la zona, con UTC como red de seguridad.

    Una zona mal escrita en una variable de entorno no puede tumbar la API. Pero
    el fallback se avisa fuerte: en UTC la ventana sigue funcionando y nadie
    notaria el problema salvo por los partidos nocturnos que faltan, que es
    justo el sintoma mas dificil de rastrear.
    """
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        logger.error(
            "Zona horaria %r no disponible; se usa UTC. Los cortes de dia van a "
            "quedar corridos. Verificar ZONA_HORARIA y que el paquete tzdata este instalado.",
            nombre,
        )
        return ZoneInfo("UTC")


def zona_del_publico() -> ZoneInfo:
    return _zona(obtener_config().zona_horaria)


def ventana_reciente(
    dias: int = DIAS_VENTANA, ahora: datetime | None = None
) -> tuple[datetime, datetime]:
    """Rango semiabierto [inicio, fin) que cubre ayer, hoy y manana.

    Se corta por dia calendario y no por "24 horas atras", para que un partido
    de ayer a la noche no desaparezca de la lista a media manana.
    """
    zona = zona_del_publico()
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(zona)
    hoy = ahora.date()

    def _limite(desplazamiento: int) -> datetime:
        # Se combina la fecha local con medianoche *en la zona* y recien despues
        # se pasa a UTC: sumar horas sobre un instante UTC daria mal el dia que
        # cambia el horario de verano.
        return datetime.combine(hoy + timedelta(days=desplazamiento), time.min, tzinfo=zona)

    return _limite(-dias).astimezone(timezone.utc), _limite(dias + 1).astimezone(timezone.utc)
