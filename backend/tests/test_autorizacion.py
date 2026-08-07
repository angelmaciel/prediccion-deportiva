"""Autorizacion por rol y proteccion de rutas.

La regla que se verifica: ningun endpoint sensible depende de que el frontend
esconda un boton. Cada uno se prueba anonimo, como usuario comun y como admin.
"""

from __future__ import annotations

import pytest

from app.modelos.usuarios import Rol
from tests.conftest import PASSWORD_VALIDA, crear_usuario, iniciar_sesion

# (metodo, ruta, cuerpo) de todo endpoint que exige rol admin.
ENDPOINTS_ADMIN = [
    ("POST", "/admin/sincronizar", None),
    ("POST", "/admin/entrenar", {"algoritmo": "logistica"}),
    ("POST", "/admin/predecir", None),
    ("POST", "/admin/backtest", {"algoritmo": "logistica"}),
    ("POST", "/admin/recalcular-metricas", None),
    ("GET", "/admin/cuotas", None),
    ("GET", "/admin/jobs", None),
    ("GET", "/admin/logs", None),
    ("GET", "/admin/estado", None),
]

ENDPOINTS_PUBLICOS = [
    "/",
    "/salud",
    "/partidos",
    "/partidos/proximos",
    "/partidos/ligas",
    "/partidos/equipos",
    "/transparencia/resumen",
    "/transparencia/jornadas",
    "/transparencia/versiones",
]


def llamar(cliente, metodo: str, ruta: str, cuerpo):
    if metodo == "GET":
        return cliente.get(ruta)
    return cliente.post(ruta, json=cuerpo) if cuerpo is not None else cliente.post(ruta)


class TestAccesoAnonimo:
    @pytest.mark.parametrize("metodo,ruta,cuerpo", ENDPOINTS_ADMIN)
    def test_admin_rechaza_anonimos(self, cliente, metodo, ruta, cuerpo):
        assert llamar(cliente, metodo, ruta, cuerpo).status_code == 401

    def test_yo_rechaza_anonimos(self, cliente):
        assert cliente.get("/auth/yo").status_code == 401

    def test_logout_rechaza_anonimos(self, cliente):
        assert cliente.post("/auth/logout").status_code == 401

    @pytest.mark.parametrize("ruta", ENDPOINTS_PUBLICOS)
    def test_lectura_publica_permitida(self, cliente, ruta):
        assert cliente.get(ruta).status_code == 200


class TestAccesoUsuarioComun:
    @pytest.mark.parametrize("metodo,ruta,cuerpo", ENDPOINTS_ADMIN)
    def test_usuario_sin_rol_admin_recibe_403(self, cliente_usuario, metodo, ruta, cuerpo):
        respuesta = llamar(cliente_usuario, metodo, ruta, cuerpo)
        assert respuesta.status_code == 403
        assert "permisos" in respuesta.json()["detail"].lower()

    def test_usuario_puede_ver_su_perfil(self, cliente_usuario):
        respuesta = cliente_usuario.get("/auth/yo")
        assert respuesta.status_code == 200
        assert respuesta.json()["rol"] == "usuario"


class TestAccesoAdmin:
    def test_admin_llega_a_los_endpoints(self, cliente_admin):
        # No se prueba el efecto (sin datos ni API keys), solo que la guarda deja pasar.
        for ruta in ["/admin/cuotas", "/admin/jobs", "/admin/logs", "/admin/estado"]:
            assert cliente_admin.get(ruta).status_code == 200

    def test_perfil_reporta_rol_admin(self, cliente_admin):
        assert cliente_admin.get("/auth/yo").json()["rol"] == "admin"

    def test_entrenar_sin_datos_devuelve_422_no_500(self, cliente_admin):
        respuesta = cliente_admin.post("/admin/entrenar", json={"algoritmo": "logistica"})
        assert respuesta.status_code == 422
        assert "partidos" in respuesta.json()["detail"]

    def test_predecir_sin_modelo_devuelve_409(self, cliente_admin):
        assert cliente_admin.post("/admin/predecir").status_code == 409


class TestSesiones:
    def test_cookie_de_sesion_es_httponly_y_samesite_strict(self, cliente, usuario_normal):
        respuesta = iniciar_sesion(cliente, "usuario@ejemplo.py")
        cookie = respuesta.headers["set-cookie"].lower()
        assert "httponly" in cookie  # inaccesible desde JavaScript
        assert "samesite=strict" in cookie  # mitiga CSRF
        assert "path=/" in cookie

    def test_el_token_no_viaja_en_el_cuerpo(self, cliente, usuario_normal):
        cuerpo = iniciar_sesion(cliente, "usuario@ejemplo.py").json()
        assert "token" not in cuerpo
        assert "password" not in cuerpo
        assert "password_hash" not in cuerpo

    def test_la_base_no_guarda_el_token_en_claro(self, cliente, usuario_normal, db):
        from app.modelos.usuarios import Sesion

        respuesta = iniciar_sesion(cliente, "usuario@ejemplo.py")
        token = respuesta.cookies.get("sesion_pd") or cliente.cookies.get("sesion_pd")
        sesion = db.query(Sesion).one()
        assert sesion.token_hash != token
        assert len(sesion.token_hash) == 64

    def test_logout_revoca_la_sesion(self, cliente_usuario):
        assert cliente_usuario.post("/auth/logout").status_code == 200
        assert cliente_usuario.get("/auth/yo").status_code == 401

    def test_cookie_invalida_no_autentica(self, cliente):
        cliente.cookies.set("sesion_pd", "token-inventado-por-un-atacante")
        assert cliente.get("/auth/yo").status_code == 401

    def test_sesion_expirada_rechazada(self, cliente, usuario_normal, db):
        from datetime import datetime, timedelta, timezone

        from app.modelos.usuarios import Sesion

        iniciar_sesion(cliente, "usuario@ejemplo.py")
        sesion = db.query(Sesion).one()
        sesion.expira_en = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert cliente.get("/auth/yo").status_code == 401

    def test_usuario_desactivado_pierde_acceso(self, cliente, usuario_normal, db):
        iniciar_sesion(cliente, "usuario@ejemplo.py")
        usuario_normal.activo = False
        db.commit()
        assert cliente.get("/auth/yo").status_code == 401

    def test_promocion_a_admin_se_refleja_en_la_sesion_vigente(self, cliente, usuario_normal, db):
        """El rol se lee de la base en cada request, no se congela en la cookie."""
        iniciar_sesion(cliente, "usuario@ejemplo.py")
        assert cliente.get("/admin/estado").status_code == 403
        usuario_normal.rol = Rol.ADMIN
        db.commit()
        assert cliente.get("/admin/estado").status_code == 200


class TestBitacora:
    def test_se_registran_logins_exitosos_y_fallidos(self, cliente, db):
        from app.modelos.auditoria import LogAcceso

        crear_usuario(db, "auditado@ejemplo.py")
        iniciar_sesion(cliente, "auditado@ejemplo.py")
        cliente.post("/auth/login", json={"email": "auditado@ejemplo.py", "password": "malaX1"})

        logins = db.query(LogAcceso).filter(LogAcceso.accion == "login").all()
        assert len(logins) == 2
        assert {log.exito for log in logins} == {True, False}

    def test_la_bitacora_no_guarda_credenciales(self, cliente, db):
        from app.modelos.auditoria import LogAcceso

        crear_usuario(db, "auditado@ejemplo.py")
        iniciar_sesion(cliente, "auditado@ejemplo.py")

        for log in db.query(LogAcceso).all():
            texto = f"{log.accion} {log.detalle or ''}"
            assert PASSWORD_VALIDA not in texto
