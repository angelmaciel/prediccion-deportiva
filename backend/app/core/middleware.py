"""Middlewares de seguridad: headers y verificacion de origen (anti-CSRF)."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import obtener_config

METODOS_MUTANTES = {"POST", "PUT", "PATCH", "DELETE"}

# La API no sirve HTML propio salvo la doc de Swagger; el CSP es restrictivo y
# solo abre lo justo para /docs.
CSP_API = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)
CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class HeadersSeguridad(BaseHTTPMiddleware):
    """Agrega los headers de seguridad a toda respuesta."""

    async def dispatch(self, request: Request, call_next):  # noqa: D102
        respuesta = await call_next(request)
        config = obtener_config()
        es_docs = request.url.path in ("/docs", "/redoc") or request.url.path.startswith(
            "/docs/"
        )
        respuesta.headers["Content-Security-Policy"] = CSP_DOCS if es_docs else CSP_API
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        respuesta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        respuesta.headers["Cross-Origin-Resource-Policy"] = "same-site"
        if config.es_produccion:
            respuesta.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return respuesta


class VerificacionOrigen(BaseHTTPMiddleware):
    """Defensa en profundidad contra CSRF.

    La cookie de sesion ya es `SameSite=Strict`, lo que corta el vector
    principal. Ademas rechazamos cualquier metodo mutante cuyo `Origin` (o
    `Referer`, si no hay Origin) no coincida con la lista blanca. Un navegador
    no permite falsear estos headers desde otro sitio.
    """

    async def dispatch(self, request: Request, call_next):  # noqa: D102
        if request.method in METODOS_MUTANTES:
            config = obtener_config()
            origen = request.headers.get("origin")
            if origen is None:
                referer = request.headers.get("referer")
                if referer:
                    partes = referer.split("/")
                    origen = "//".join([partes[0], partes[2]]) if len(partes) > 2 else None
            # Sin Origin ni Referer: cliente no-navegador (curl, tests, cron interno).
            # No hay riesgo de CSRF porque no hay cookie enviada automaticamente.
            if origen is not None and origen not in config.lista_origenes:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detalle": "Origen no permitido"},
                )
        return await call_next(request)
