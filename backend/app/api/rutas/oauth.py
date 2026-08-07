"""Ingreso con Google (OAuth 2.0, flujo de codigo de autorizacion).

Decisiones:
- El codigo se canjea **servidor a servidor**: el navegador nunca ve el client
  secret ni el access token de Google. Lo unico que recibe es la misma cookie
  de sesion opaca que emite el ingreso por formulario.
- No se valida la firma del `id_token`: no hace falta. Los datos del usuario se
  piden al endpoint `userinfo` de Google por HTTPS con el access token recien
  obtenido, asi que la fuente ya es confiable y nos ahorramos manejar JWKS.
- Solo se acepta un email con `email_verified`. Sin eso, cualquiera que registre
  ese email en su propio proveedor podria quedarse con una cuenta existente.
- El parametro `state` viaja en una cookie aparte con `SameSite=Lax`: la cookie
  de sesion es `Strict` y el navegador no la mandaria en la vuelta desde Google,
  que es una navegacion cross-site.

Si no hay credenciales configuradas, los endpoints responden 404 y la app
funciona igual con el formulario.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import registrar_acceso
from app.api.sesiones import crear_sesion, establecer_cookie
from app.core.config import obtener_config
from app.core.crypto import indice_ciego, normalizar_email
from app.db.session import obtener_db
from app.modelos.usuarios import Proveedor, Rol, Usuario

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["autenticacion"])

AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_CANJE = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

COOKIE_ESTADO = "oauth_estado_pd"
VIGENCIA_ESTADO = 600  # 10 minutos para completar el rodeo


def _configurado() -> bool:
    config = obtener_config()
    return bool(config.google_client_id and config.google_client_secret)


def _exigir_configurado() -> None:
    if not _configurado():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El ingreso con Google no esta configurado en este entorno",
        )


def _volver_al_front(motivo: str | None = None) -> RedirectResponse:
    """Vuelve siempre al front: un JSON de error en la barra del navegador no
    le sirve a nadie. Si algo fallo, vuelve al ingreso con el motivo como
    parametro para que la SPA lo explique en castellano."""
    base = obtener_config().url_frontend.rstrip("/")
    destino = base if motivo is None else f"{base}/ingreso?" + urlencode({"error": motivo})
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/inicio")
def inicio() -> RedirectResponse:
    """Manda al usuario a Google con un `state` de un solo uso."""
    _exigir_configurado()
    config = obtener_config()
    estado = secrets.token_urlsafe(32)

    parametros = {
        "client_id": config.google_client_id,
        "redirect_uri": config.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": estado,
        "prompt": "select_account",
    }
    respuesta = RedirectResponse(
        f"{AUTORIZACION}?{urlencode(parametros)}", status_code=status.HTTP_303_SEE_OTHER
    )
    respuesta.set_cookie(
        key=COOKIE_ESTADO,
        value=estado,
        max_age=VIGENCIA_ESTADO,
        httponly=True,
        secure=config.cookie_segura,
        # Lax y no Strict: Strict no sobrevive a la vuelta desde accounts.google.com.
        samesite="lax",
        path="/auth/google",
    )
    return respuesta


def _canjear_codigo(codigo: str) -> str:
    """Cambia el codigo de un solo uso por un access token. Devuelve el token."""
    config = obtener_config()
    try:
        respuesta = httpx.post(
            URL_CANJE,
            data={
                "code": codigo,
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "redirect_uri": config.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"no se pudo contactar a Google: {exc}") from exc
    if respuesta.status_code >= 400:
        raise RuntimeError(f"Google rechazo el codigo ({respuesta.status_code})")
    token = respuesta.json().get("access_token")
    if not token:
        raise RuntimeError("Google no devolvio access_token")
    return token


def _datos_del_usuario(access_token: str) -> tuple[str, str]:
    """Devuelve (sub, email) verificados. Lanza RuntimeError si no sirven."""
    try:
        respuesta = httpx.get(
            USERINFO, headers={"Authorization": f"Bearer {access_token}"}, timeout=15.0
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"no se pudo leer el perfil: {exc}") from exc
    if respuesta.status_code >= 400:
        raise RuntimeError(f"Google rechazo la lectura del perfil ({respuesta.status_code})")

    datos = respuesta.json()
    sub, email = datos.get("sub"), datos.get("email")
    if not sub or not email:
        raise RuntimeError("el perfil de Google vino incompleto")
    if not datos.get("email_verified"):
        raise RuntimeError("el email no esta verificado en Google")
    return str(sub), normalizar_email(email)


def _resolver_usuario(db: Session, sub: str, email: str) -> Usuario:
    """Encuentra la cuenta o la crea. Vincula por `sub`, y si no, por email."""
    usuario = db.execute(select(Usuario).where(Usuario.proveedor_sub == sub)).scalar_one_or_none()
    if usuario is not None:
        return usuario

    usuario = db.execute(
        select(Usuario).where(Usuario.email_indice == indice_ciego(email))
    ).scalar_one_or_none()
    if usuario is not None:
        # Cuenta preexistente con el mismo email verificado: se vincula y se le
        # deja la contrasena, asi puede entrar por cualquiera de los dos lados.
        usuario.proveedor_sub = sub
        return usuario

    usuario = Usuario(
        email=email,
        email_indice=indice_ciego(email),
        password_hash=None,  # no hay contrasena que verificar
        rol=Rol.USUARIO,
        proveedor=Proveedor.GOOGLE,
        proveedor_sub=sub,
    )
    db.add(usuario)
    db.flush()
    return usuario


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(obtener_db),
) -> Response:
    _exigir_configurado()

    if error or not code:
        return _volver_al_front("cancelado")

    esperado = request.cookies.get(COOKIE_ESTADO)
    if not esperado or not state or not secrets.compare_digest(esperado, state):
        # State que no coincide: o expiro el intento, o alguien lo esta forzando.
        registrar_acceso(db, "login_google", request, exito=False, detalle="state invalido")
        db.commit()
        return _volver_al_front("expirado")

    try:
        sub, email = _datos_del_usuario(_canjear_codigo(code))
    except RuntimeError as exc:
        logger.warning("Ingreso con Google fallido: %s", exc)
        registrar_acceso(db, "login_google", request, exito=False, detalle=str(exc)[:200])
        db.commit()
        return _volver_al_front("fallo")

    usuario = _resolver_usuario(db, sub, email)

    if not usuario.activo:
        registrar_acceso(
            db,
            "login_google",
            request,
            usuario_id=usuario.id,
            exito=False,
            detalle="cuenta inactiva",
        )
        db.commit()
        return _volver_al_front("inactiva")

    if usuario.totp_activo:
        # El 2FA propio no se puede pedir en medio del redirect sin inventar un
        # estado intermedio. Antes que saltearlo en silencio, se manda al
        # formulario, que si lo exige.
        registrar_acceso(
            db, "login_google", request, usuario_id=usuario.id, exito=False, detalle="2FA activo"
        )
        db.commit()
        return _volver_al_front("2fa")

    token = crear_sesion(db, usuario, request)
    registrar_acceso(db, "login_google", request, usuario_id=usuario.id)
    db.commit()

    respuesta = _volver_al_front()
    respuesta.status_code = status.HTTP_303_SEE_OTHER
    establecer_cookie(respuesta, token)
    respuesta.delete_cookie(COOKIE_ESTADO, path="/auth/google")
    return respuesta
