"""Partidos y predicciones. Lectura publica, servida siempre desde la base propia."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import obtener_db
from app.esquemas import (
    CruceH2H,
    EquipoH2H,
    EquipoSalida,
    EscenarioSalida,
    FactorSalida,
    HistorialH2H,
    PaginaPartidos,
    PartidoDeRacha,
    PartidoSalida,
    PrediccionSalida,
    PromediosH2H,
    RachaEquipo,
    SenialSalida,
    VeredictoSalida,
)
from app.ml.mercados import ResultadoEscenario
from app.modelos.futbol import Equipo, EstadoPartido, Partido
from app.modelos.prediccion import Prediccion
from app.servicios.h2h import (
    LIMITE_POR_DEFECTO,
    ResumenEquipo,
    con_estadisticas,
    desde_la_optica_de,
    enfrentamientos_previos,
    resumir,
    ultimos_partidos,
)
from app.servicios.predicciones import ModeloNoDisponible, modelo_activo
from app.servicios.veredicto import SinModelo, construir_veredicto

router = APIRouter(prefix="/partidos", tags=["partidos"])

MAX_POR_PAGINA = 100


def _ultimas_predicciones(db: Session, ids: list[int]) -> dict[int, Prediccion]:
    """Ultima prediccion por partido, en una sola consulta."""
    if not ids:
        return {}
    predicciones = db.execute(
        select(Prediccion)
        .where(Prediccion.partido_id.in_(ids))
        .order_by(Prediccion.partido_id.asc(), Prediccion.creado_en.asc(), Prediccion.id.asc())
    ).scalars()
    # Al recorrer en orden ascendente, la ultima escritura de cada clave gana.
    return {p.partido_id: p for p in predicciones}


def _a_salida(partido: Partido, prediccion: Prediccion | None) -> PartidoSalida:
    return PartidoSalida(
        id=partido.id,
        fecha=partido.fecha,
        liga=partido.liga,
        temporada=partido.temporada,
        jornada=partido.jornada,
        estado=partido.estado.value,
        equipo_local=EquipoSalida.model_validate(partido.equipo_local),
        equipo_visitante=EquipoSalida.model_validate(partido.equipo_visitante),
        goles_local=partido.goles_local,
        goles_visitante=partido.goles_visitante,
        resultado_real=partido.resultado_real.value if partido.resultado_real else None,
        prediccion=(
            PrediccionSalida(
                prob_local=prediccion.prob_local,
                prob_empate=prediccion.prob_empate,
                prob_visitante=prediccion.prob_visitante,
                marcador_probable_local=prediccion.marcador_probable_local,
                marcador_probable_visitante=prediccion.marcador_probable_visitante,
                modelo_version=prediccion.modelo_version,
                resultado_predicho=prediccion.resultado_predicho,
                confianza=prediccion.confianza,
                creado_en=prediccion.creado_en,
            )
            if prediccion
            else None
        ),
    )


@router.get("", response_model=PaginaPartidos)
def listar_partidos(
    request: Request,
    db: Session = Depends(obtener_db),
    liga: str | None = Query(default=None, max_length=80),
    estado: EstadoPartido | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    pagina: int = Query(default=1, ge=1, le=1000),
    por_pagina: int = Query(default=20, ge=1, le=MAX_POR_PAGINA),
) -> PaginaPartidos:
    """Listado paginado con filtros. Todos los parametros se validan con Pydantic."""
    filtros = []
    if liga:
        filtros.append(Partido.liga == liga)
    if estado:
        filtros.append(Partido.estado == estado)
    if desde:
        filtros.append(Partido.fecha >= desde)
    if hasta:
        filtros.append(Partido.fecha <= hasta)

    total = db.execute(select(func.count(Partido.id)).where(*filtros)).scalar_one()
    partidos = list(
        db.execute(
            select(Partido)
            .where(*filtros)
            .order_by(Partido.fecha.desc(), Partido.id.desc())
            .offset((pagina - 1) * por_pagina)
            .limit(por_pagina)
        )
        .unique()
        .scalars()
    )
    predicciones = _ultimas_predicciones(db, [p.id for p in partidos])
    return PaginaPartidos(
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        items=[_a_salida(p, predicciones.get(p.id)) for p in partidos],
    )


@router.get("/proximos", response_model=list[PartidoSalida])
def proximos_partidos(
    request: Request,
    db: Session = Depends(obtener_db),
    dias: int = Query(default=7, ge=1, le=30),
    liga: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=50, ge=1, le=MAX_POR_PAGINA),
) -> list[PartidoSalida]:
    """Partidos programados con su prediccion vigente."""
    ahora = datetime.now(timezone.utc)
    filtros = [
        Partido.estado == EstadoPartido.PROGRAMADO,
        Partido.fecha >= ahora,
        Partido.fecha <= ahora + timedelta(days=dias),
    ]
    if liga:
        filtros.append(Partido.liga == liga)

    partidos = list(
        db.execute(select(Partido).where(*filtros).order_by(Partido.fecha.asc()).limit(limite))
        .unique()
        .scalars()
    )
    predicciones = _ultimas_predicciones(db, [p.id for p in partidos])
    return [_a_salida(p, predicciones.get(p.id)) for p in partidos]


@router.get("/ligas", response_model=list[str])
def listar_ligas(request: Request, db: Session = Depends(obtener_db)) -> list[str]:
    return list(db.execute(select(Partido.liga).distinct().order_by(Partido.liga)).scalars())


@router.get("/equipos", response_model=list[EquipoSalida])
def listar_equipos(
    request: Request,
    db: Session = Depends(obtener_db),
    liga: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=100, ge=1, le=500),
) -> list[Equipo]:
    consulta = select(Equipo).order_by(Equipo.nombre).limit(limite)
    if liga:
        consulta = consulta.where(Equipo.liga == liga)
    return list(db.execute(consulta).scalars())


@router.get("/{partido_id}", response_model=PartidoSalida)
def detalle_partido(
    request: Request, partido_id: int, db: Session = Depends(obtener_db)
) -> PartidoSalida:
    partido = db.get(Partido, partido_id)
    if partido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado")
    predicciones = _ultimas_predicciones(db, [partido.id])
    return _a_salida(partido, predicciones.get(partido.id))


def _a_escenario(escenario: ResultadoEscenario) -> EscenarioSalida:
    return EscenarioSalida(
        claves=list(escenario.claves),
        etiqueta=escenario.etiqueta,
        probabilidad=escenario.probabilidad,
        probabilidad_ingenua=escenario.probabilidad_ingenua,
        correlacion=escenario.correlacion,
    )


@router.get("/{partido_id}/veredicto", response_model=VeredictoSalida)
def veredicto_partido(
    request: Request, partido_id: int, db: Session = Depends(obtener_db)
) -> VeredictoSalida:
    """Lectura unica del partido combinando la logistica y el Poisson."""
    partido = db.get(Partido, partido_id)
    if partido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado")

    try:
        modelo, _version = modelo_activo(db)
        veredicto = construir_veredicto(partido, modelo, db=db)
    except (ModeloNoDisponible, SinModelo) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return VeredictoSalida(
        partido_id=veredicto.partido_id,
        resultado=veredicto.resultado,
        etiqueta=veredicto.etiqueta,
        probabilidad=veredicto.probabilidad,
        confianza=veredicto.confianza,
        consenso=veredicto.consenso,
        prob_logistica=list(veredicto.prob_logistica),
        prob_poisson=list(veredicto.prob_poisson),
        marcador_probable=(
            list(veredicto.marcador_probable[:2]) if veredicto.marcador_probable else None
        ),
        prob_marcador_probable=(
            veredicto.marcador_probable[2] if veredicto.marcador_probable else None
        ),
        factores=[
            FactorSalida(nombre=f.nombre, detalle=f.detalle, favorece=f.favorece)
            for f in veredicto.factores
        ],
        escenarios_simples=[_a_escenario(e) for e in veredicto.escenarios_simples],
        escenarios_combinados=[_a_escenario(e) for e in veredicto.escenarios_combinados],
        senales=[
            SenialSalida(nombre=s.nombre, detalle=s.detalle, favorece=s.favorece, peso=s.peso)
            for s in veredicto.senales
        ],
    )


def _a_racha(
    db: Session,
    partido: Partido,
    equipo: Equipo,
    localia: str | None,
    liga: str | None,
    limite: int,
) -> RachaEquipo:
    """Racha reciente de un equipo contra cualquier rival."""
    previos = ultimos_partidos(
        db, equipo.id, partido.fecha, localia=localia, liga=liga, limite=limite
    )
    resumen = resumir(previos, equipo.id, equipo.nombre)
    return RachaEquipo(
        equipo_id=equipo.id,
        nombre=equipo.nombre,
        jugados=resumen.jugados,
        ganados=resumen.ganados,
        empatados=resumen.empatados,
        perdidos=resumen.perdidos,
        promedios=PromediosH2H(
            **{clave: acumulador.promedio for clave, acumulador in resumen.metricas.items()}
        ),
        partidos_con_estadisticas=con_estadisticas(previos),
        partidos=[PartidoDeRacha(**desde_la_optica_de(previo, equipo.id)) for previo in previos],
    )


def _a_equipo_h2h(resumen: ResumenEquipo) -> EquipoH2H:
    return EquipoH2H(
        equipo_id=resumen.equipo_id,
        nombre=resumen.nombre,
        jugados=resumen.jugados,
        ganados=resumen.ganados,
        empatados=resumen.empatados,
        perdidos=resumen.perdidos,
        promedios=PromediosH2H(
            **{clave: acumulador.promedio for clave, acumulador in resumen.metricas.items()}
        ),
    )


@router.get("/{partido_id}/h2h", response_model=HistorialH2H)
def historial_h2h(
    request: Request,
    partido_id: int,
    db: Session = Depends(obtener_db),
    solo_misma_localia: bool = Query(
        default=False,
        description="Solo los cruces en los que el local de este partido tambien fue local",
    ),
    liga: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=LIMITE_POR_DEFECTO, ge=1, le=50),
) -> HistorialH2H:
    """Enfrentamientos directos anteriores a este partido, con promedios."""
    partido = db.get(Partido, partido_id)
    if partido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado")

    previos = enfrentamientos_previos(
        db, partido, solo_misma_localia=solo_misma_localia, liga=liga, limite=limite
    )

    return HistorialH2H(
        partido_id=partido.id,
        solo_misma_localia=solo_misma_localia,
        liga=liga,
        total_cruces=len(previos),
        cruces_con_estadisticas=con_estadisticas(previos),
        local=_a_equipo_h2h(resumir(previos, partido.equipo_local_id, partido.equipo_local.nombre)),
        visitante=_a_equipo_h2h(
            resumir(previos, partido.equipo_visitante_id, partido.equipo_visitante.nombre)
        ),
        cruces=[
            CruceH2H(
                partido_id=previo.id,
                fecha=previo.fecha,
                liga=previo.liga,
                temporada=previo.temporada,
                local=previo.equipo_local.nombre,
                visitante=previo.equipo_visitante.nombre,
                goles_local=previo.goles_local,
                goles_visitante=previo.goles_visitante,
                tiene_estadisticas=previo.estadisticas is not None,
            )
            for previo in previos
        ],
        # Con el filtro de localia activo, a cada equipo se lo mira en la
        # condicion en que va a jugar este partido: el local de local y el
        # visitante de visitante.
        racha_local=_a_racha(
            db,
            partido,
            partido.equipo_local,
            "local" if solo_misma_localia else None,
            liga,
            limite,
        ),
        racha_visitante=_a_racha(
            db,
            partido,
            partido.equipo_visitante,
            "visitante" if solo_misma_localia else None,
            liga,
            limite,
        ),
    )
