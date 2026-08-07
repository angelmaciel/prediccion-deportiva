"""Sincronizacion de las APIs externas hacia la base propia.

Regla del proyecto: el frontend nunca llama a las APIs externas. Este modulo
corre desde el scheduler (1-2 veces al dia) y deja todo cacheado en Postgres.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.modelos.auditoria import EjecucionJob
from app.modelos.futbol import Equipo, EstadoPartido, Fuente, Partido, Resultado
from app.servicios.ingesta.api_football import ClienteApiFootball
from app.servicios.ingesta.csv_historico import (
    DIVISIONES,
    buscar_equipo_existente,
    importar_division,
    recordar_equipo,
)
from app.servicios.ingesta.cuota import ControlCuota, CuotaAgotada
from app.servicios.ingesta.football_data import (
    COMPETICIONES,
    ClienteFootballData,
    EquipoCrudo,
    ErrorFuenteExterna,
    PartidoCrudo,
)

logger = logging.getLogger(__name__)

# Ventana sincronizada en cada corrida: resultados recientes + calendario proximo.
DIAS_HACIA_ATRAS = 10
DIAS_HACIA_ADELANTE = 21


def obtener_o_crear_equipo(db: Session, crudo: EquipoCrudo, fuente: Fuente) -> Equipo:
    equipo = db.execute(
        select(Equipo).where(Equipo.fuente == fuente, Equipo.external_id == crudo.external_id)
    ).scalar_one_or_none()

    if equipo is None:
        # Antes de crear uno nuevo, ver si el club ya esta cargado por otra
        # fuente. Sin este paso cada equipo terminaba duplicado: el CSV deja
        # "Arsenal" con diez temporadas encima y la API crea "Arsenal FC" en
        # blanco al lado. Los partidos que vienen apuntan al registro nuevo, con
        # lo que el modelo predice a ciegas sobre un equipo sin historia y el
        # cara a cara sale vacio — y nada de eso da error, solo probabilidades
        # de un tercio para cada resultado.
        equipo = buscar_equipo_existente(db, crudo.nombre, crudo.pais)
        if equipo is not None:
            logger.info(
                "Equipo reconciliado: '%s' ya estaba cargado como '%s'",
                crudo.nombre,
                equipo.nombre,
            )
            # Pasa a identificarse por el id de esta fuente. Lo que importa es
            # que conserva su id interno, y con el toda su historia.
            equipo.fuente = fuente
            equipo.external_id = crudo.external_id
            if crudo.nombre_corto:
                equipo.nombre_corto = crudo.nombre_corto

    if equipo is None:
        equipo = Equipo(
            nombre=crudo.nombre,
            nombre_corto=crudo.nombre_corto,
            liga=crudo.liga,
            pais=crudo.pais,
            escudo_url=crudo.escudo_url,
            fuente=fuente,
            external_id=crudo.external_id,
        )
        db.add(equipo)
        db.flush()
        # Al indice tambien, o el siguiente partido de este mismo equipo no lo
        # encontraria y crearia otro duplicado.
        recordar_equipo(db, equipo)
    else:
        # Los nombres y escudos cambian entre temporadas; mantenerlos frescos.
        equipo.nombre = crudo.nombre
        equipo.liga = crudo.liga
        if crudo.escudo_url:
            equipo.escudo_url = crudo.escudo_url
    return equipo


def calcular_resultado(goles_local: int | None, goles_visitante: int | None) -> Resultado | None:
    if goles_local is None or goles_visitante is None:
        return None
    if goles_local > goles_visitante:
        return Resultado.LOCAL
    if goles_local < goles_visitante:
        return Resultado.VISITANTE
    return Resultado.EMPATE


def guardar_partido(db: Session, crudo: PartidoCrudo, fuente: Fuente) -> tuple[Partido, bool]:
    """Upsert de un partido. Devuelve (partido, era_nuevo)."""
    local = obtener_o_crear_equipo(db, crudo.local, fuente)
    visitante = obtener_o_crear_equipo(db, crudo.visitante, fuente)

    partido = db.execute(
        select(Partido).where(Partido.fuente == fuente, Partido.external_id == crudo.external_id)
    ).scalar_one_or_none()
    nuevo = partido is None
    if nuevo:
        partido = Partido(fuente=fuente, external_id=crudo.external_id)
        db.add(partido)

    estado = EstadoPartido(crudo.estado)
    partido.equipo_local_id = local.id
    partido.equipo_visitante_id = visitante.id
    partido.fecha = crudo.fecha
    partido.liga = crudo.liga
    partido.temporada = crudo.temporada
    partido.jornada = crudo.jornada
    partido.estado = estado
    partido.goles_local = crudo.goles_local
    partido.goles_visitante = crudo.goles_visitante
    partido.resultado_real = (
        calcular_resultado(crudo.goles_local, crudo.goles_visitante)
        if estado == EstadoPartido.FINALIZADO
        else None
    )
    db.flush()
    return partido, nuevo


def sincronizar_europa(
    db: Session, cliente: ClienteFootballData | None = None, ventana: bool = True
) -> int:
    """Sincroniza las competiciones europeas del plan gratuito.

    Con `ventana=False` trae la temporada en curso completa en lugar del rango
    de fechas habitual: mismo costo en requests (1 por competicion) pero da el
    historico de resultados que el entrenamiento necesita.
    """
    cliente = cliente or ClienteFootballData()
    if not cliente.configurado:
        logger.info("football-data.org sin token: se omite la sincronizacion europea")
        return 0

    desde = hasta = None
    if ventana:
        hoy = datetime.now(timezone.utc).date()
        desde = (hoy - timedelta(days=DIAS_HACIA_ATRAS)).isoformat()
        hasta = (hoy + timedelta(days=DIAS_HACIA_ADELANTE)).isoformat()

    total = 0
    for codigo in COMPETICIONES:
        try:
            crudos = cliente.partidos_de_competicion(codigo, desde, hasta)
        except ErrorFuenteExterna as exc:
            # Una competicion caida no debe abortar el resto de la sincronizacion.
            logger.error("No se pudo sincronizar %s: %s", codigo, exc)
            continue
        for crudo in crudos:
            guardar_partido(db, crudo, Fuente.FOOTBALL_DATA)
            total += 1
        logger.info("Sincronizados %d partidos de %s", len(crudos), codigo)
    return total


def sincronizar_paraguay(
    db: Session, cliente: ClienteApiFootball | None = None, temporada: int | None = None
) -> int:
    """Sincroniza la Primera Division de Paraguay (1 request por temporada)."""
    config = obtener_config()
    if cliente is None:
        control = ControlCuota(db, Fuente.API_FOOTBALL, config.api_football_cuota_diaria)
        cliente = ClienteApiFootball(control)
    if not cliente.configurado:
        logger.info("API-Football sin clave: se omite la sincronizacion de Paraguay")
        return 0

    temporada = temporada or datetime.now(timezone.utc).year
    try:
        crudos = cliente.partidos_temporada(temporada)
    except (ErrorFuenteExterna, CuotaAgotada) as exc:
        logger.error("No se pudo sincronizar Paraguay: %s", exc)
        return 0

    for crudo in crudos:
        guardar_partido(db, crudo, Fuente.API_FOOTBALL)
    logger.info("Sincronizados %d partidos de Paraguay (%s)", len(crudos), temporada)
    return len(crudos)


def importar_historico_csv(
    db: Session, temporadas: list[str], divisiones: list[str] | None = None
) -> int:
    """Carga el historico de football-data.co.uk (CSV publicos, sin credenciales).

    Se hace aparte de la sincronizacion diaria: es una carga puntual y pesada
    que solo aporta partidos ya jugados.
    """
    divisiones = divisiones or list(DIVISIONES)
    total = 0
    for division in divisiones:
        if division not in DIVISIONES:
            logger.error("Division desconocida: %s", division)
            continue
        for temporada in temporadas:
            try:
                resultado = importar_division(db, division, temporada)
            except FileNotFoundError:
                # Temporada aun no publicada o liga sin datos ese anio.
                logger.info("%s %s: no publicado", division, temporada)
                continue
            except Exception as exc:  # noqa: BLE001 - una division caida no aborta el resto
                logger.error("Fallo %s %s: %s", division, temporada, exc)
                continue
            db.commit()
            total += resultado.partidos_nuevos
            logger.info(
                "%s %s: %d nuevos, %d actualizados",
                division,
                temporada,
                resultado.partidos_nuevos,
                resultado.partidos_actualizados,
            )
            for creado in resultado.equipos_creados:
                logger.info("  equipo nuevo en %s: %s", division, creado)
    return total


def sincronizar_todo(db: Session) -> int:
    """Corrida completa de sincronizacion, registrada en `ejecuciones_job`."""
    ejecucion = EjecucionJob(job="sincronizacion", inicio=datetime.now(timezone.utc))
    db.add(ejecucion)
    db.flush()
    try:
        total = sincronizar_europa(db) + sincronizar_paraguay(db)
        ejecucion.exito = True
        ejecucion.registros_afectados = total
        ejecucion.mensaje = f"{total} partidos sincronizados"
    except Exception as exc:  # noqa: BLE001 - se registra y se re-lanza
        ejecucion.exito = False
        ejecucion.mensaje = str(exc)[:500]
        ejecucion.fin = datetime.now(timezone.utc)
        db.commit()
        raise
    ejecucion.fin = datetime.now(timezone.utc)
    db.commit()
    return ejecucion.registros_afectados
