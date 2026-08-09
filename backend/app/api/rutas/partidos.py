"""Partidos y predicciones. Lectura publica, servida siempre desde la base propia."""

from __future__ import annotations

from datetime import datetime

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
    NarrativaSalida,
    PaginaPartidos,
    PartidoDeRacha,
    PartidoSalida,
    PromediosH2H,
    RachaEquipo,
    SenialSalida,
    VeredictoSalida,
)
from app.ml.mercados import ResultadoEscenario
from app.modelos.futbol import Equipo, EstadoPartido, Partido
from app.modelos.prediccion import NarrativaPartido
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
from app.servicios.serializacion import (
    a_salida,
    listado_con_predicciones,
    ultimas_predicciones,
)
from app.servicios.ventana import ventana_reciente
from app.servicios.veredicto import SinModelo, construir_veredicto

router = APIRouter(prefix="/partidos", tags=["partidos"])

MAX_POR_PAGINA = 100


@router.get("", response_model=PaginaPartidos)
def listar_partidos(
    request: Request,
    db: Session = Depends(obtener_db),
    liga: str | None = Query(default=None, max_length=80),
    estado: EstadoPartido | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    historico: bool = Query(
        default=False,
        description="Levanta la ventana de ayer/hoy/manana y busca en todo el historico",
    ),
    pagina: int = Query(default=1, ge=1, le=1000),
    por_pagina: int = Query(default=20, ge=1, le=MAX_POR_PAGINA),
) -> PaginaPartidos:
    """Listado paginado con filtros. Todos los parametros se validan con Pydantic.

    Sin rango explicito devuelve solo ayer, hoy y manana. Para ir mas atras hay
    que pedirlo: `historico=true` o un `desde`/`hasta` propio.
    """
    filtros = []
    if liga:
        filtros.append(Partido.liga == liga)
    if estado:
        filtros.append(Partido.estado == estado)
    if desde:
        filtros.append(Partido.fecha >= desde)
    if hasta:
        filtros.append(Partido.fecha <= hasta)
    if not historico and desde is None and hasta is None:
        inicio, fin = ventana_reciente()
        filtros.extend([Partido.fecha >= inicio, Partido.fecha < fin])

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
    return PaginaPartidos(
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
        items=listado_con_predicciones(db, partidos),
    )


@router.get("/proximos", response_model=list[PartidoSalida])
def proximos_partidos(
    request: Request,
    db: Session = Depends(obtener_db),
    dias: int = Query(
        default=1,
        ge=1,
        le=30,
        description="Dias hacia atras y hacia adelante alrededor de hoy (1 = ayer, hoy y manana)",
    ),
    liga: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=50, ge=1, le=MAX_POR_PAGINA),
) -> list[PartidoSalida]:
    """Partidos programados con su prediccion vigente.

    La ventana arranca al inicio de ayer, no en `ahora`: un partido de anoche
    que la fuente todavia no cerro sigue siendo informacion util, y cortar por
    dia calendario evita que la lista cambie sola a lo largo del dia.
    """
    inicio, fin = ventana_reciente(dias)
    filtros = [
        Partido.estado == EstadoPartido.PROGRAMADO,
        Partido.fecha >= inicio,
        Partido.fecha < fin,
    ]
    if liga:
        filtros.append(Partido.liga == liga)

    partidos = list(
        db.execute(select(Partido).where(*filtros).order_by(Partido.fecha.asc()).limit(limite))
        .unique()
        .scalars()
    )
    return listado_con_predicciones(db, partidos)


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
    predicciones = ultimas_predicciones(db, [partido.id])
    return a_salida(partido, predicciones.get(partido.id))


@router.get("/{partido_id}/narrativa", response_model=NarrativaSalida)
def narrativa_partido(
    request: Request, partido_id: int, db: Session = Depends(obtener_db)
) -> NarrativaSalida:
    """Analisis en prosa del partido, si ya fue generado.

    Solo lee. Generarlo cuesta dinero por token, asi que se hace desde el job
    o desde el panel de admin, nunca en una visita publica.
    """
    narrativa = (
        db.query(NarrativaPartido).filter(NarrativaPartido.partido_id == partido_id).one_or_none()
    )
    if narrativa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todavia no hay analisis narrativo para este partido",
        )
    return NarrativaSalida(
        partido_id=narrativa.partido_id,
        texto=narrativa.texto,
        modelo=narrativa.modelo,
        fuentes=narrativa.fuentes or [],
        creado_en=narrativa.creado_en,
    )


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
