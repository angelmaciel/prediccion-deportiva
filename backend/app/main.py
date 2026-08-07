"""Punto de entrada de la API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.rutas import admin, auth, oauth, partidos, transparencia
from app.core.config import obtener_config
from app.core.limites import limiter
from app.core.middleware import HeadersSeguridad, VerificacionOrigen
from app.scheduler import detener_scheduler, iniciar_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

config = obtener_config()

DESCRIPCION = """
API de analisis y prediccion de resultados de futbol.

**Aviso importante:** las probabilidades publicadas son estimaciones
estadisticas calculadas sobre datos historicos. No son garantias de resultado.
Este proyecto es exclusivamente analitico: no gestiona dinero, no intermedia
apuestas y no redirige a casas de apuestas.
"""


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    iniciar_scheduler()
    yield
    detener_scheduler()


app = FastAPI(
    title=config.nombre_app,
    description=DESCRIPCION,
    version="0.1.0",
    lifespan=ciclo_de_vida,
    # La doc interactiva se apaga en produccion: no hace falta exponer el mapa
    # completo de endpoints administrativos.
    docs_url=None if config.es_produccion else "/docs",
    redoc_url=None if config.es_produccion else "/redoc",
    openapi_url=None if config.es_produccion else "/openapi.json",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(HeadersSeguridad)
app.add_middleware(VerificacionOrigen)

# CORS explicito: solo el dominio del frontend, con credenciales habilitadas
# porque la sesion viaja en cookie. Nunca "*" (seria incompatible con cookies
# ademas de inseguro).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.lista_origenes,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)


@app.exception_handler(RateLimitExceeded)
async def manejar_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Demasiadas solicitudes. Esperar un momento antes de reintentar."},
    )


@app.exception_handler(Exception)
async def manejar_error_no_previsto(request: Request, exc: Exception) -> JSONResponse:
    # El detalle queda en el log del servidor; al cliente se le devuelve un
    # mensaje generico para no filtrar rutas, consultas ni versiones.
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servidor"},
    )


app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(partidos.router)
app.include_router(transparencia.router)
app.include_router(admin.router)


@app.get("/salud", tags=["sistema"])
def salud() -> dict:
    return {"estado": "ok", "entorno": config.entorno}


@app.get("/", tags=["sistema"])
def raiz() -> dict:
    return {
        "nombre": config.nombre_app,
        "version": "0.1.0",
        "aviso": (
            "Las predicciones son estimaciones estadisticas, no garantias. "
            "Proyecto analitico: no gestiona dinero ni apuestas."
        ),
        "documentacion": "/docs" if not config.es_produccion else None,
    }
