"""Ventana de fechas por defecto para los listados publicos.

Las tres secciones que ve un visitante (proximos partidos, resultados e
historial de aciertos) muestran por defecto solo ayer, hoy y manana. La base
guarda temporadas enteras, y traerlas siempre entera es lo que hacia lenta la
carga inicial: el 99 % de las visitas mira los partidos de la fecha.

El historico completo sigue disponible, pero hay que pedirlo explicitamente
(`historico=true` o un rango `desde`/`hasta`), asi el costo lo paga solo quien
lo consulta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Dias hacia atras y hacia adelante alrededor de hoy.
DIAS_VENTANA = 1


def ventana_reciente(
    dias: int = DIAS_VENTANA, ahora: datetime | None = None
) -> tuple[datetime, datetime]:
    """Rango semiabierto [inicio, fin) que cubre ayer, hoy y manana en UTC.

    Se corta por dia calendario y no por "24 horas atras", para que un partido
    de ayer a la noche no desaparezca de la lista a media manana.
    """
    ahora = ahora or datetime.now(timezone.utc)
    inicio_de_hoy = ahora.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return inicio_de_hoy - timedelta(days=dias), inicio_de_hoy + timedelta(days=dias + 1)
