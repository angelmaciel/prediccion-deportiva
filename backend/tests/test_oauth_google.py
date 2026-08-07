"""Ingreso con Google.

Lo que se prueba es la seguridad del rodeo, no la felicidad del camino feliz:
que sin `state` valido no se abra sesion, que un email sin verificar no sirva
para adueniarse de una cuenta, y que el 2FA propio no quede salteado.
"""

from __future__ import annotations

import pytest

from app.api.rutas import oauth
from app.core.crypto import indice_ciego, normalizar_email
from app.core.seguridad import hashear_password
from app.modelos.usuarios import Proveedor, Rol, Usuario

EMAIL = "hincha@example.com"
SUB = "108124098127349871234"


@pytest.fixture
def google_configurado(monkeypatch):
    """Hace creer a la app que hay credenciales cargadas."""
    monkeypatch.setattr(oauth, "_configurado", lambda: True)


@pytest.fixture
def google_responde(monkeypatch):
    """Reemplaza las dos llamadas salientes a Google."""

    def configurar(sub: str = SUB, email: str = EMAIL, verificado: bool = True):
        monkeypatch.setattr(oauth, "_canjear_codigo", lambda codigo: "access-token-falso")

        def _perfil(token: str) -> tuple[str, str]:
            if not verificado:
                raise RuntimeError("el email no esta verificado en Google")
            return sub, normalizar_email(email)

        monkeypatch.setattr(oauth, "_datos_del_usuario", _perfil)

    return configurar


def _iniciar(cliente) -> str:
    """Arranca el rodeo y devuelve el `state` que quedo en la cookie."""
    respuesta = cliente.get("/auth/google/inicio", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"].startswith("https://accounts.google.com/")
    return cliente.cookies[oauth.COOKIE_ESTADO]


class TestDisponibilidad:
    def test_sin_credenciales_no_se_ofrece(self, cliente):
        assert cliente.get("/auth/proveedores").json() == {"google": False}

    def test_sin_credenciales_los_endpoints_no_existen(self, cliente):
        assert cliente.get("/auth/google/inicio", follow_redirects=False).status_code == 404

    def test_con_credenciales_se_ofrece(self, cliente, google_configurado, monkeypatch):
        from app.core.config import obtener_config

        config = obtener_config()
        monkeypatch.setattr(config, "google_client_id", "id-falso")
        monkeypatch.setattr(config, "google_client_secret", "secreto-falso")
        assert cliente.get("/auth/proveedores").json() == {"google": True}


class TestEstado:
    def test_sin_state_no_abre_sesion(self, cliente, google_configurado, google_responde):
        google_responde()
        respuesta = cliente.get(
            "/auth/google/callback?code=abc&state=inventado", follow_redirects=False
        )
        assert respuesta.status_code == 303
        assert "error=expirado" in respuesta.headers["location"]
        assert cliente.get("/auth/yo").status_code == 401

    def test_state_que_no_coincide_no_abre_sesion(
        self, cliente, google_configurado, google_responde
    ):
        google_responde()
        _iniciar(cliente)
        respuesta = cliente.get(
            "/auth/google/callback?code=abc&state=otro-distinto", follow_redirects=False
        )
        assert "error=expirado" in respuesta.headers["location"]
        assert cliente.get("/auth/yo").status_code == 401

    def test_si_el_usuario_cancela_vuelve_sin_sesion(self, cliente, google_configurado):
        respuesta = cliente.get(
            "/auth/google/callback?error=access_denied", follow_redirects=False
        )
        assert "error=cancelado" in respuesta.headers["location"]
        assert cliente.get("/auth/yo").status_code == 401


class TestAlta:
    def test_crea_la_cuenta_y_abre_sesion(
        self, cliente, db, google_configurado, google_responde
    ):
        google_responde()
        estado = _iniciar(cliente)
        respuesta = cliente.get(
            f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False
        )
        assert respuesta.status_code == 303
        assert "error=" not in respuesta.headers["location"]

        yo = cliente.get("/auth/yo")
        assert yo.status_code == 200
        assert yo.json()["email"] == EMAIL

        usuario = db.query(Usuario).filter(Usuario.proveedor_sub == SUB).one()
        assert usuario.proveedor == Proveedor.GOOGLE
        assert usuario.password_hash is None
        assert usuario.rol == Rol.USUARIO

    def test_email_sin_verificar_se_rechaza(
        self, cliente, db, google_configurado, google_responde
    ):
        google_responde(verificado=False)
        estado = _iniciar(cliente)
        respuesta = cliente.get(
            f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False
        )
        assert "error=fallo" in respuesta.headers["location"]
        assert db.query(Usuario).count() == 0

    def test_entrar_dos_veces_no_duplica_la_cuenta(
        self, cliente, db, google_configurado, google_responde
    ):
        google_responde()
        for _ in range(2):
            estado = _iniciar(cliente)
            cliente.get(f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False)
        assert db.query(Usuario).count() == 1


class TestCuentaExistente:
    def _crear_local(self, db, totp: bool = False, activo: bool = True) -> Usuario:
        usuario = Usuario(
            email=EMAIL,
            email_indice=indice_ciego(EMAIL),
            password_hash=hashear_password("Contrasena-Larga-1"),
            rol=Rol.USUARIO,
            activo=activo,
            totp_activo=totp,
        )
        db.add(usuario)
        db.commit()
        return usuario

    def test_vincula_por_email_verificado_sin_duplicar(
        self, cliente, db, google_configurado, google_responde
    ):
        self._crear_local(db)
        google_responde()
        estado = _iniciar(cliente)
        cliente.get(f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False)

        assert db.query(Usuario).count() == 1
        usuario = db.query(Usuario).one()
        assert usuario.proveedor_sub == SUB
        # La contrasena sigue estando: puede entrar por cualquiera de los dos lados.
        assert usuario.password_hash is not None

    def test_una_cuenta_con_2fa_no_se_saltea_el_segundo_factor(
        self, cliente, db, google_configurado, google_responde
    ):
        self._crear_local(db, totp=True)
        google_responde()
        estado = _iniciar(cliente)
        respuesta = cliente.get(
            f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False
        )
        assert "error=2fa" in respuesta.headers["location"]
        assert cliente.get("/auth/yo").status_code == 401

    def test_una_cuenta_desactivada_no_entra(
        self, cliente, db, google_configurado, google_responde
    ):
        self._crear_local(db, activo=False)
        google_responde()
        estado = _iniciar(cliente)
        respuesta = cliente.get(
            f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False
        )
        assert "error=inactiva" in respuesta.headers["location"]
        assert cliente.get("/auth/yo").status_code == 401


class TestLoginPorFormulario:
    def test_una_cuenta_de_google_no_entra_con_contrasena_vacia(
        self, cliente, db, google_configurado, google_responde
    ):
        """Sin `password_hash` el login por formulario tiene que fallar igual."""
        google_responde()
        estado = _iniciar(cliente)
        cliente.get(f"/auth/google/callback?code=abc&state={estado}", follow_redirects=False)

        respuesta = cliente.post("/auth/login", json={"email": EMAIL, "password": "cualquiera"})
        assert respuesta.status_code == 401
