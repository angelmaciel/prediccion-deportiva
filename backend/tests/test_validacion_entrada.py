"""Validacion de entrada y comportamiento defensivo de la API.

Cubre: esquemas Pydantic estrictos, mensajes que no filtran informacion,
headers de seguridad, verificacion de origen y rate limiting.
"""

from __future__ import annotations

import pytest

from tests.conftest import PASSWORD_VALIDA, crear_usuario, iniciar_sesion


class TestValidacionRegistro:
    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"email": "no-es-un-email", "password": PASSWORD_VALIDA},
            {"email": "", "password": PASSWORD_VALIDA},
            {"email": "sin-arroba.py", "password": PASSWORD_VALIDA},
            {"password": PASSWORD_VALIDA},  # falta email
            {"email": "a@b.py"},  # falta password
            {},
        ],
    )
    def test_entradas_invalidas_dan_422(self, cliente, cuerpo):
        assert cliente.post("/auth/registro", json=cuerpo).status_code == 422

    @pytest.mark.parametrize(
        "password",
        ["corta1A", "todominusculas123", "TODOMAYUSCULAS123", "SinNumerosAca", "12345678901234"],
    )
    def test_contrasenas_debiles_rechazadas(self, cliente, password):
        respuesta = cliente.post(
            "/auth/registro", json={"email": "nuevo@ejemplo.py", "password": password}
        )
        assert respuesta.status_code == 422

    def test_campos_extra_rechazados(self, cliente):
        """`extra=forbid`: no se puede intentar setear el rol desde el request."""
        respuesta = cliente.post(
            "/auth/registro",
            json={"email": "escalada@ejemplo.py", "password": PASSWORD_VALIDA, "rol": "admin"},
        )
        assert respuesta.status_code == 422

    def test_registro_valido_crea_usuario_comun(self, cliente):
        respuesta = cliente.post(
            "/auth/registro", json={"email": "nuevo@ejemplo.py", "password": PASSWORD_VALIDA}
        )
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["rol"] == "usuario"  # nunca admin por autoservicio
        assert "password" not in cuerpo and "password_hash" not in cuerpo

    def test_email_duplicado_no_confirma_la_cuenta_existente(self, cliente, db):
        crear_usuario(db, "existente@ejemplo.py")
        respuesta = cliente.post(
            "/auth/registro", json={"email": "existente@ejemplo.py", "password": PASSWORD_VALIDA}
        )
        assert respuesta.status_code == 409
        assert "existente@ejemplo.py" not in respuesta.text
        assert "ya existe" not in respuesta.text.lower()


class TestMensajesDeLogin:
    def test_mismo_mensaje_para_email_inexistente_y_password_incorrecta(self, cliente, db):
        crear_usuario(db, "real@ejemplo.py")
        inexistente = cliente.post(
            "/auth/login", json={"email": "fantasma@ejemplo.py", "password": PASSWORD_VALIDA}
        )
        password_mala = cliente.post(
            "/auth/login", json={"email": "real@ejemplo.py", "password": "OtraCosa123456"}
        )
        assert inexistente.status_code == password_mala.status_code == 401
        assert inexistente.json()["detail"] == password_mala.json()["detail"]

    def test_el_mensaje_no_nombra_el_email(self, cliente):
        respuesta = cliente.post(
            "/auth/login", json={"email": "fantasma@ejemplo.py", "password": PASSWORD_VALIDA}
        )
        assert "fantasma" not in respuesta.text


class TestValidacionListados:
    @pytest.mark.parametrize(
        "params",
        [
            {"pagina": 0},
            {"pagina": -5},
            {"por_pagina": 0},
            {"por_pagina": 5000},  # por encima del maximo permitido
            {"estado": "estado-inventado"},
            {"desde": "no-es-fecha"},
        ],
    )
    def test_parametros_invalidos_dan_422(self, cliente, params):
        assert cliente.get("/partidos", params=params).status_code == 422

    def test_partido_inexistente_da_404(self, cliente):
        assert cliente.get("/partidos/999999").status_code == 404

    def test_id_no_numerico_da_422(self, cliente):
        assert cliente.get("/partidos/no-numerico").status_code == 422

    def test_intento_de_inyeccion_sql_no_rompe_ni_filtra(self, cliente, equipos):
        """El ORM parametriza: el payload se trata como texto, no como SQL."""
        respuesta = cliente.get("/partidos", params={"liga": "'; DROP TABLE partidos; --"})
        assert respuesta.status_code == 200
        assert respuesta.json()["total"] == 0
        # La tabla sigue viva.
        assert cliente.get("/partidos").status_code == 200

    def test_dias_fuera_de_rango(self, cliente):
        assert cliente.get("/partidos/proximos", params={"dias": 999}).status_code == 422
        assert cliente.get("/partidos/proximos", params={"dias": 0}).status_code == 422


class TestValidacionAdmin:
    def test_algoritmo_invalido_rechazado(self, cliente_admin):
        respuesta = cliente_admin.post("/admin/entrenar", json={"algoritmo": "red-neuronal-magica"})
        assert respuesta.status_code == 422

    def test_campos_extra_rechazados(self, cliente_admin):
        respuesta = cliente_admin.post(
            "/admin/entrenar", json={"algoritmo": "logistica", "trampa": True}
        )
        assert respuesta.status_code == 422


class TestCacheDeLecturaPublica:
    """Los GET publicos se marcan cacheables; lo que depende del usuario, no."""

    @pytest.mark.parametrize("ruta", ["/partidos", "/partidos/ligas", "/transparencia/resumen"])
    def test_las_lecturas_publicas_se_pueden_cachear(self, cliente, ruta):
        assert cliente.get(ruta).headers["Cache-Control"] == (
            "public, max-age=120, stale-while-revalidate=600"
        )

    def test_lo_que_depende_de_la_sesion_no_se_marca_publico(self, cliente):
        # Marcar `public` una respuesta con datos de un usuario la filtraria a la
        # cache compartida del siguiente visitante.
        assert "Cache-Control" not in cliente.get("/auth/yo").headers

    def test_un_error_no_se_cachea(self, cliente):
        # Cachear un 404 dejaria el partido inaccesible hasta que venza el TTL,
        # incluso despues de que la sincronizacion lo cargue.
        assert "Cache-Control" not in cliente.get("/partidos/999999").headers


class TestHeadersDeSeguridad:
    def test_headers_presentes(self, cliente):
        headers = cliente.get("/salud").headers
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "Content-Security-Policy" in headers

    def test_csp_de_la_api_es_restrictiva(self, cliente):
        csp = cliente.get("/salud").headers["Content-Security-Policy"]
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_hsts_solo_en_produccion(self, cliente):
        # En test/desarrollo se sirve por HTTP; anunciar HSTS romperia el entorno.
        assert "Strict-Transport-Security" not in cliente.get("/salud").headers


class TestVerificacionOrigen:
    def test_origen_ajeno_rechazado_en_metodos_mutantes(self, cliente, usuario_normal):
        respuesta = cliente.post(
            "/auth/login",
            json={"email": "usuario@ejemplo.py", "password": PASSWORD_VALIDA},
            headers={"Origin": "https://sitio-malicioso.example"},
        )
        assert respuesta.status_code == 403

    def test_origen_permitido_aceptado(self, cliente, usuario_normal):
        respuesta = cliente.post(
            "/auth/login",
            json={"email": "usuario@ejemplo.py", "password": PASSWORD_VALIDA},
            headers={"Origin": "http://localhost:5173"},
        )
        assert respuesta.status_code == 200

    def test_lecturas_no_se_bloquean_por_origen(self, cliente):
        respuesta = cliente.get("/salud", headers={"Origin": "https://sitio-malicioso.example"})
        assert respuesta.status_code == 200


class TestRateLimiting:
    def test_login_se_bloquea_tras_varios_intentos(self, cliente, usuario_normal, limiter_activo):
        """5 intentos cada 15 minutos por IP: frena el fuerza bruta."""
        codigos = [
            cliente.post(
                "/auth/login", json={"email": "usuario@ejemplo.py", "password": "Incorrecta123"}
            ).status_code
            for _ in range(7)
        ]
        assert 429 in codigos
        assert codigos.count(401) <= 5

    def test_el_bloqueo_alcanza_tambien_a_las_credenciales_correctas(
        self, cliente, usuario_normal, limiter_activo
    ):
        for _ in range(6):
            cliente.post(
                "/auth/login", json={"email": "usuario@ejemplo.py", "password": "Incorrecta123"}
            )
        assert iniciar_sesion(cliente, "usuario@ejemplo.py").status_code == 429


class TestUrlDeBaseDeDatos:
    """Render y otros PaaS inyectan la URL sin driver; el engine no arranca asi."""

    @pytest.mark.parametrize(
        "inyectada,esperada",
        [
            (
                "postgres://u:p@host:5432/db",
                "postgresql+psycopg://u:p@host:5432/db",
            ),
            (
                "postgresql://u:p@host:5432/db",
                "postgresql+psycopg://u:p@host:5432/db",
            ),
            (
                "postgresql+psycopg://u:p@host:5432/db",
                "postgresql+psycopg://u:p@host:5432/db",
            ),
        ],
    )
    def test_se_fuerza_el_driver_psycopg(self, inyectada, esperada):
        from app.core.config import Config

        assert Config(database_url=inyectada).database_url == esperada

    def test_no_toca_sqlite(self):
        """Los tests corren sobre SQLite: el normalizador no debe alcanzarlo."""
        from app.core.config import Config

        assert Config(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"
