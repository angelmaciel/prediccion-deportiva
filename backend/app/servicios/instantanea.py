"""Instantanea estatica de la ventana, para que la portada no dependa de la API.

El servicio web corre en el plan gratuito de Render, que lo duerme tras unos
minutos sin trafico. La primera visita despues de eso paga el arranque en frio
completo — decenas de segundos — y ninguna optimizacion de consulta se nota al
lado de eso.

La salida de esto es un JSON que el job diario deja junto al sitio estatico. La
portada lo lee del CDN y pinta al instante, sin backend y sin base, y recien
despues revalida contra la API. Es el mismo patron que usan los sitios de
resultados: la grilla del dia es identica para todos los visitantes, asi que se
genera una vez y se sirve desde el borde, no se recalcula por visita.

La ventana que se exporta es mas ancha que la que sirve la API a proposito: el
archivo se genera una vez al dia, pero se sigue leyendo cuando ya paso la
medianoche, y para entonces "manana" ya es hoy. Con el margen extra el archivo
envejece sin quedar vacio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.futbol import EstadoPartido, Partido
from app.servicios.serializacion import listado_con_predicciones
from app.servicios.ventana import ventana_reciente

# Margen sobre la ventana de la API (que es +-1 dia), para que el archivo siga
# sirviendo despues de que el dia cambie.
DIAS_INSTANTANEA = 3

# Tope de partidos por seccion. Es una cota de seguridad para que un dia con
# muchas competiciones no genere un archivo enorme que tarde mas en bajar de lo
# que tardaria la propia API.
MAX_POR_SECCION = 120


def construir_instantanea(
    db: Session, dias: int = DIAS_INSTANTANEA, ahora: datetime | None = None
) -> dict[str, Any]:
    ahora = ahora or datetime.now(timezone.utc)
    inicio, fin = ventana_reciente(dias, ahora)
    en_ventana = (Partido.fecha >= inicio, Partido.fecha < fin)

    def _traer(*filtros, descendente: bool) -> list[Partido]:
        orden = Partido.fecha.desc() if descendente else Partido.fecha.asc()
        return list(
            db.execute(
                select(Partido)
                .where(*en_ventana, *filtros)
                .order_by(orden)
                .limit(MAX_POR_SECCION)
            )
            .unique()
            .scalars()
        )

    proximos = _traer(
        Partido.estado.in_((EstadoPartido.PROGRAMADO, EstadoPartido.EN_JUEGO)),
        descendente=False,
    )
    resultados = _traer(
        Partido.estado == EstadoPartido.FINALIZADO,
        Partido.resultado_real.is_not(None),
        descendente=True,
    )
    ligas = list(db.execute(select(Partido.liga).distinct().order_by(Partido.liga)).scalars())

    return {
        # El frontend usa esto para decidir si el archivo todavia sirve o si
        # conviene esperar a la API. Sin el, no habria forma de distinguir una
        # instantanea de hoy de una de la semana pasada.
        "generado_en": ahora.isoformat(),
        "dias": dias,
        "ligas": ligas,
        "proximos": [p.model_dump(mode="json") for p in listado_con_predicciones(db, proximos)],
        "resultados": [
            p.model_dump(mode="json") for p in listado_con_predicciones(db, resultados)
        ],
    }
