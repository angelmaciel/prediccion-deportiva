"""Cifrado de columnas, indice ciego y hasheo de contrasenas."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.crypto import (
    cifrar,
    descifrar,
    hash_token,
    indice_ciego,
    normalizar_email,
)
from app.core.seguridad import (
    generar_secreto_totp,
    generar_token_sesion,
    hashear_password,
    validar_fortaleza_password,
    verificar_password,
    verificar_totp,
)
from app.modelos.usuarios import Usuario
from tests.conftest import crear_usuario


class TestCifradoColumnas:
    def test_ida_y_vuelta(self):
        assert descifrar(cifrar("angel@ejemplo.py")) == "angel@ejemplo.py"

    def test_dos_cifrados_del_mismo_texto_difieren(self):
        # Nonce aleatorio por operacion: sin esto, dos usuarios con el mismo
        # email tendrian el mismo ciphertext y eso ya seria una filtracion.
        assert cifrar("igual@ejemplo.py") != cifrar("igual@ejemplo.py")

    def test_texto_cifrado_no_contiene_el_original(self):
        assert "angel" not in cifrar("angel@ejemplo.py")

    def test_manipulacion_detectada(self):
        # AES-GCM autentica: alterar un byte tiene que fallar, no devolver basura.
        cifrado = cifrar("dato@ejemplo.py")
        alterado = ("A" if cifrado[20] != "A" else "B").join([cifrado[:20], cifrado[21:]])
        with pytest.raises(Exception):  # noqa: B017
            descifrar(alterado)


class TestIndiceCiego:
    def test_determinista(self):
        assert indice_ciego("angel@ejemplo.py") == indice_ciego("angel@ejemplo.py")

    def test_normaliza_mayusculas_y_espacios(self):
        assert indice_ciego("  Angel@Ejemplo.PY ") == indice_ciego("angel@ejemplo.py")

    def test_distingue_emails_distintos(self):
        assert indice_ciego("a@ejemplo.py") != indice_ciego("b@ejemplo.py")

    def test_no_revela_el_email(self):
        indice = indice_ciego("angel@ejemplo.py")
        assert "angel" not in indice and "@" not in indice
        assert len(indice) == 64  # hex de SHA-256


class TestPasswords:
    def test_hash_no_guarda_la_contrasena(self):
        hash_ = hashear_password("ContrasenaSegura123")
        assert "ContrasenaSegura123" not in hash_
        assert hash_.startswith("$argon2")

    def test_dos_hashes_de_la_misma_contrasena_difieren(self):
        assert hashear_password("Misma123456") != hashear_password("Misma123456")

    def test_verificacion_correcta_e_incorrecta(self):
        hash_ = hashear_password("ContrasenaSegura123")
        assert verificar_password("ContrasenaSegura123", hash_) is True
        assert verificar_password("otra-cosa", hash_) is False

    def test_usuario_inexistente_devuelve_false_sin_explotar(self):
        # Se hashea contra un senuelo para no filtrar por temporizacion.
        assert verificar_password("cualquiera", None) is False

    @pytest.mark.parametrize(
        "password,regla",
        [
            ("Corta1", "12 caracteres"),
            ("todominuscula123", "mayuscula"),
            ("TODOMAYUSCULA123", "minuscula"),
            ("SinNumerosAqui", "numero"),
        ],
    )
    def test_reglas_de_fortaleza(self, password, regla):
        fallas = validar_fortaleza_password(password)
        assert any(regla in f for f in fallas), fallas

    def test_contrasena_valida_no_tiene_fallas(self):
        assert validar_fortaleza_password("ContrasenaSegura123") == []


class TestTokens:
    def test_tokens_unicos_y_largos(self):
        tokens = {generar_token_sesion() for _ in range(50)}
        assert len(tokens) == 50
        assert all(len(t) >= 40 for t in tokens)

    def test_hash_token_es_irreversible_y_estable(self):
        token = generar_token_sesion()
        assert hash_token(token) == hash_token(token)
        assert token not in hash_token(token)


class TestTotp:
    def test_codigo_valido_y_basura(self):
        import pyotp

        secreto = generar_secreto_totp()
        assert verificar_totp(secreto, pyotp.TOTP(secreto).now()) is True
        assert verificar_totp(secreto, "000000") is False
        assert verificar_totp(secreto, "no-numerico") is False
        assert verificar_totp(secreto, "") is False


class TestPersistenciaCifrada:
    def test_email_se_guarda_cifrado_en_la_base(self, db):
        """El ORM descifra al leer, pero la columna cruda no debe ser legible."""
        crear_usuario(db, "secreto@ejemplo.py")

        recuperado = db.query(Usuario).one()
        assert recuperado.email == "secreto@ejemplo.py"

        # SQL crudo: consultar via el ORM pasaria por el TypeDecorator y
        # descifraria, con lo cual el test no probaria nada.
        crudo = db.execute(text("SELECT email FROM usuarios")).scalar_one()
        assert crudo != "secreto@ejemplo.py"
        assert "secreto" not in crudo
        assert descifrar(crudo) == "secreto@ejemplo.py"

    def test_busqueda_por_indice_ciego(self, db):
        usuario = crear_usuario(db, "Buscado@Ejemplo.PY")
        encontrado = (
            db.query(Usuario)
            .filter(Usuario.email_indice == indice_ciego("buscado@ejemplo.py"))
            .one()
        )
        assert encontrado.id == usuario.id
        assert encontrado.email == normalizar_email("Buscado@Ejemplo.PY")
