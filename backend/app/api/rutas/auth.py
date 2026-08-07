"""Registro, login, logout y 2FA.

Decisiones de seguridad visibles en este modulo:
- El token de sesion viaja en cookie HttpOnly + SameSite=Strict; nunca se
  devuelve en el body, asi ningun JS (ni un XSS) puede leerlo.
- El login responde siempre el mismo mensaje generico: no revela si el email
  existe, si la contrasena es incorrecta o si falta el segundo factor.
- Rate limit propio de 5 intentos cada 15 minutos por IP, mas bloqueo temporal
  por cuenta tras intentos fallidos repetidos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import asegurar_utc, registrar_acceso, usuario_actual
from app.api.sesiones import crear_sesion, establecer_cookie
from app.core.config import obtener_config
from app.core.crypto import hash_token, indice_ciego, normalizar_email
from app.core.limites import clave_login, limiter
from app.core.seguridad import (
    generar_secreto_totp,
    hashear_password,
    necesita_rehash,
    uri_provisioning_totp,
    verificar_password,
    verificar_totp,
)
from app.db.session import obtener_db
from app.esquemas import (
    LoginEntrada,
    MensajeSalida,
    ProveedoresSalida,
    RegistroEntrada,
    TotpAltaSalida,
    TotpConfirmacionEntrada,
    UsuarioSalida,
)
from app.modelos.usuarios import Rol, Sesion, Usuario

router = APIRouter(prefix="/auth", tags=["autenticacion"])

MENSAJE_CREDENCIALES = "Email o contrasena incorrectos"
MAX_INTENTOS_CUENTA = 10
BLOQUEO_MINUTOS = 15


def _buscar_por_email(db: Session, email: str) -> Usuario | None:
    return db.execute(
        select(Usuario).where(Usuario.email_indice == indice_ciego(email))
    ).scalar_one_or_none()


@router.post("/registro", response_model=UsuarioSalida, status_code=status.HTTP_201_CREATED)
@limiter.limit(obtener_config().limite_registro)
def registrar(
    request: Request, datos: RegistroEntrada, db: Session = Depends(obtener_db)
) -> Usuario:
    email = normalizar_email(datos.email)
    if _buscar_por_email(db, email) is not None:
        registrar_acceso(db, "registro", request, exito=False, detalle="email ya registrado")
        db.commit()
        # Mismo status que un alta valida no serviria (devolvemos el usuario),
        # asi que se usa un 409 sin detalle adicional sobre la cuenta existente.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo completar el registro con esos datos",
        )

    usuario = Usuario(
        email=email,
        email_indice=indice_ciego(email),
        password_hash=hashear_password(datos.password),
        rol=Rol.USUARIO,
    )
    db.add(usuario)
    db.flush()
    registrar_acceso(db, "registro", request, usuario_id=usuario.id)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/login", response_model=UsuarioSalida)
@limiter.limit(obtener_config().limite_login, key_func=clave_login)
def login(
    request: Request,
    respuesta: Response,
    datos: LoginEntrada,
    db: Session = Depends(obtener_db),
) -> Usuario:
    email = normalizar_email(datos.email)
    usuario = _buscar_por_email(db, email)

    # Se verifica siempre, incluso sin usuario: `verificar_password` gasta el
    # mismo tiempo contra un hash senuelo para no filtrar por temporizacion.
    password_ok = verificar_password(datos.password, usuario.password_hash if usuario else None)

    if usuario is not None:
        bloqueado_hasta = asegurar_utc(usuario.bloqueado_hasta)
        if bloqueado_hasta and bloqueado_hasta > datetime.now(timezone.utc):
            registrar_acceso(
                db, "login", request, usuario_id=usuario.id, exito=False, detalle="cuenta bloqueada"
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos fallidos. Probar de nuevo en unos minutos.",
            )

    if usuario is None or not password_ok or not usuario.activo:
        if usuario is not None:
            usuario.intentos_fallidos += 1
            if usuario.intentos_fallidos >= MAX_INTENTOS_CUENTA:
                usuario.bloqueado_hasta = datetime.now(timezone.utc) + timedelta(
                    minutes=BLOQUEO_MINUTOS
                )
                usuario.intentos_fallidos = 0
        registrar_acceso(
            db,
            "login",
            request,
            usuario_id=usuario.id if usuario else None,
            exito=False,
            detalle="credenciales invalidas",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_CREDENCIALES)

    if usuario.totp_activo:
        if not datos.codigo_totp or not verificar_totp(usuario.totp_secreto, datos.codigo_totp):
            registrar_acceso(
                db, "login", request, usuario_id=usuario.id, exito=False, detalle="2FA invalido"
            )
            db.commit()
            # Mensaje generico: no confirma que la contrasena fuera correcta.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=MENSAJE_CREDENCIALES
            )

    # Si los parametros de argon2 cambiaron, se aprovecha el login para migrar.
    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hashear_password(datos.password)

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    token = crear_sesion(db, usuario, request)
    registrar_acceso(db, "login", request, usuario_id=usuario.id)
    db.commit()
    db.refresh(usuario)

    establecer_cookie(respuesta, token)
    return usuario


@router.post("/logout", response_model=MensajeSalida)
def logout(
    request: Request,
    respuesta: Response,
    db: Session = Depends(obtener_db),
    usuario: Usuario = Depends(usuario_actual),
) -> MensajeSalida:
    token = request.cookies.get(obtener_config().cookie_nombre)
    if token:
        sesion = db.execute(
            select(Sesion).where(Sesion.token_hash == hash_token(token))
        ).scalar_one_or_none()
        if sesion is not None:
            sesion.revocada = True
    registrar_acceso(db, "logout", request, usuario_id=usuario.id)
    db.commit()
    respuesta.delete_cookie(obtener_config().cookie_nombre, path="/")
    return MensajeSalida(mensaje="Sesion cerrada")


@router.get("/yo", response_model=UsuarioSalida)
def yo(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    return usuario


@router.get("/proveedores", response_model=ProveedoresSalida)
def proveedores() -> ProveedoresSalida:
    """Que formas de ingreso ofrece este entorno.

    El front lo consulta para no mostrar un boton de Google que llevaria a un
    404 si no hay credenciales cargadas.
    """
    config = obtener_config()
    return ProveedoresSalida(google=bool(config.google_client_id and config.google_client_secret))


@router.post("/2fa/alta", response_model=TotpAltaSalida)
def alta_2fa(
    request: Request,
    db: Session = Depends(obtener_db),
    usuario: Usuario = Depends(usuario_actual),
) -> TotpAltaSalida:
    """Genera el secreto TOTP. Queda inactivo hasta confirmarlo con un codigo."""
    if usuario.totp_activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El 2FA ya esta activo en esta cuenta"
        )
    secreto = generar_secreto_totp()
    usuario.totp_secreto = secreto  # se guarda cifrado (columna TextoCifrado)
    usuario.totp_activo = False
    registrar_acceso(db, "2fa_alta", request, usuario_id=usuario.id)
    db.commit()
    return TotpAltaSalida(
        secreto=secreto, uri_provisioning=uri_provisioning_totp(secreto, usuario.email)
    )


@router.post("/2fa/confirmar", response_model=MensajeSalida)
def confirmar_2fa(
    request: Request,
    datos: TotpConfirmacionEntrada,
    db: Session = Depends(obtener_db),
    usuario: Usuario = Depends(usuario_actual),
) -> MensajeSalida:
    if not usuario.totp_secreto:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Primero hay que dar de alta el 2FA"
        )
    if not verificar_totp(usuario.totp_secreto, datos.codigo):
        registrar_acceso(db, "2fa_confirmar", request, usuario_id=usuario.id, exito=False)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Codigo invalido")
    usuario.totp_activo = True
    registrar_acceso(db, "2fa_confirmar", request, usuario_id=usuario.id)
    db.commit()
    return MensajeSalida(mensaje="2FA activado")
