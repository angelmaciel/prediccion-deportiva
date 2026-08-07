"""Control y monitoreo del consumo de cuota de las APIs externas.

API-Football regala 100 requests/dia y football-data.org 10/minuto. Si nos
pasamos, la cuenta queda bloqueada, asi que cada request se contabiliza en la
tabla `consumo_cuota` y el cliente consulta el presupuesto restante *antes* de
salir a la red.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.auditoria import ConsumoCuota
from app.modelos.futbol import Fuente

logger = logging.getLogger(__name__)


class CuotaAgotada(RuntimeError):
    """Se alcanzo el limite diario de la fuente; no se debe seguir pidiendo."""


class ControlCuota:
    """Contador diario persistido por fuente."""

    def __init__(self, db: Session, fuente: Fuente, limite_diario: int) -> None:
        self.db = db
        self.fuente = fuente
        self.limite_diario = limite_diario

    def _registro(self, dia: date | None = None) -> ConsumoCuota:
        dia = dia or datetime.now(timezone.utc).date()
        registro = self.db.execute(
            select(ConsumoCuota).where(
                ConsumoCuota.fuente == self.fuente, ConsumoCuota.dia == dia
            )
        ).scalar_one_or_none()
        if registro is None:
            registro = ConsumoCuota(fuente=self.fuente, dia=dia, requests=0, errores=0)
            self.db.add(registro)
            self.db.flush()
        return registro

    def restante(self) -> int:
        return max(0, self.limite_diario - self._registro().requests)

    def verificar(self, cantidad: int = 1) -> None:
        if self.restante() < cantidad:
            raise CuotaAgotada(
                f"Cuota diaria agotada para {self.fuente.value} "
                f"({self.limite_diario} requests). Reintentar manana."
            )

    def consumir(self, cantidad: int = 1, error: bool = False) -> None:
        registro = self._registro()
        registro.requests += cantidad
        if error:
            registro.errores += 1
        registro.ultimo_request = datetime.now(timezone.utc)
        self.db.flush()
        if registro.requests >= self.limite_diario * 0.9:
            logger.warning(
                "Cuota de %s al %d%% (%d/%d)",
                self.fuente.value,
                int(100 * registro.requests / self.limite_diario),
                registro.requests,
                self.limite_diario,
            )


class LimitadorPorMinuto:
    """Ventana deslizante en memoria para respetar los N requests/minuto.

    Si la ventana esta llena, duerme lo justo hasta que se libere un espacio en
    lugar de arriesgar un 429.
    """

    def __init__(self, maximo_por_minuto: int) -> None:
        self.maximo = maximo_por_minuto
        self._marcas: deque[float] = deque()

    def esperar_turno(self) -> None:
        ahora = time.monotonic()
        while self._marcas and ahora - self._marcas[0] >= 60:
            self._marcas.popleft()
        if len(self._marcas) >= self.maximo:
            espera = 60 - (ahora - self._marcas[0]) + 0.25
            logger.info("Rate limit local: esperando %.1fs antes del proximo request", espera)
            time.sleep(max(0.0, espera))
            return self.esperar_turno()
        self._marcas.append(time.monotonic())
