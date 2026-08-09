"""Configuracion de la aplicacion.

Todo secreto se lee de variables de entorno; nada queda hardcodeado en el
repositorio. En produccion la app se niega a arrancar si detecta valores por
defecto inseguros (ver `validar_para_produccion`).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDERS_INSEGUROS = (
    "cambiar-por",
    "changeme",
    "secret",
    "test",
)


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General ---
    entorno: Literal["development", "test", "production"] = "development"
    debug: bool = False
    nombre_app: str = "Prediccion Deportiva API"

    # Zona en la que se decide que es "ayer", "hoy" y "manana". Tiene que ser la
    # del publico, no UTC: un partido a las 21:00 en Asuncion ya es del dia
    # siguiente en UTC, y con la ventana calculada en UTC se caia de la lista
    # justo en el horario de mayor interes.
    zona_horaria: str = "America/Asuncion"

    # --- Base de datos ---
    database_url: str = "postgresql+psycopg://prediccion:prediccion@localhost:5432/prediccion"

    # --- Criptografia ---
    secret_key: str = Field(
        default="dev-secret-key-no-usar-en-produccion-1234567890", min_length=32
    )
    # base64 de b"clave-aes-256-solo-para-dev-0000" (exactamente 32 bytes)
    clave_cifrado_datos: str = "Y2xhdmUtYWVzLTI1Ni1zb2xvLXBhcmEtZGV2LTAwMDA="
    clave_indice_ciego: str = "dev-blind-index-key-no-usar-en-produccion"

    # --- Sesiones ---
    sesion_duracion_horas: int = 12
    cookie_segura: bool = False
    cookie_nombre: str = "sesion_pd"

    # --- CORS ---
    origenes_permitidos: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Rate limiting ---
    limite_general: str = "120/minute"
    limite_login: str = "5/15minutes"
    limite_admin: str = "30/minute"
    limite_registro: str = "3/hour"

    # --- APIs externas ---
    football_data_token: str = ""
    football_data_rpm: int = 10
    football_data_base: str = "https://api.football-data.org/v4"
    api_football_key: str = ""
    api_football_host: str = "v3.football.api-sports.io"
    api_football_cuota_diaria: int = 100

    # --- Ingreso con Google (OAuth 2.0) ---
    # Vacios = el boton no se ofrece y los endpoints responden 404. La app
    # arranca igual: el ingreso con formulario no depende de esto.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Tiene que coincidir caracter por caracter con la URI autorizada que se
    # carga en Google Cloud Console, o Google rechaza el intercambio.
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # A donde vuelve el navegador despues del rodeo por Google.
    url_frontend: str = "http://localhost:5173"

    # --- Analisis narrativo (Claude) ---
    # Sin clave el endpoint responde 404 y la app funciona igual: la narrativa
    # es un agregado opcional sobre el analisis estadistico, no un requisito.
    anthropic_api_key: str = ""
    anthropic_modelo: str = "claude-opus-5"
    # low | medium | high | xhigh | max. Un analisis largo con juicio sobre
    # datos que se contradicen justifica "high"; bajarlo abarata y acorta.
    anthropic_esfuerzo: str = "high"
    # Techo de salida por partido. Con busqueda web la respuesta puede tardar
    # minutos, por eso el cliente usa streaming.
    anthropic_max_tokens: int = 8000
    # La busqueda web es lo que permite hablar de lesiones, sanciones y
    # convocatorias: datos que la base no tiene. Se cobra aparte.
    anthropic_busqueda_web: bool = True

    # --- Scheduler ---
    scheduler_activo: bool = False
    sincronizacion_cron_horas: str = "3,15"
    reentrenamiento_dia_semana: str = "mon"
    reentrenamiento_hora: int = 4

    # --- ML ---
    directorio_artefactos: str = "artefactos"
    minimo_partidos_entrenamiento: int = 200

    # --- Bootstrap admin ---
    admin_email_inicial: str = ""
    admin_password_inicial: str = ""

    @field_validator("database_url")
    @classmethod
    def _driver_explicito(cls, v: str) -> str:
        """Fuerza el driver psycopg 3 en la URL de PostgreSQL.

        Render (y Heroku, y varios PaaS) inyectan la URL como `postgres://` o
        `postgresql://`, sin driver. SQLAlchemy 2 resuelve `postgres://` a un
        dialecto que ya no existe y `postgresql://` a psycopg2, que este
        proyecto no instala — usa psycopg 3. En ambos casos la app no arranca,
        y el error habla de un dialecto o un modulo, no de la URL, asi que
        cuesta relacionarlo con la variable de entorno.
        """
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @field_validator("origenes_permitidos")
    @classmethod
    def _sin_comodin(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("ORIGENES_PERMITIDOS no admite comodines; listar dominios explicitos")
        return v

    @property
    def lista_origenes(self) -> list[str]:
        return [o.strip() for o in self.origenes_permitidos.split(",") if o.strip()]

    @property
    def horas_sincronizacion(self) -> list[int]:
        return [int(h) for h in self.sincronizacion_cron_horas.split(",") if h.strip()]

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "production"

    def clave_aes(self) -> bytes:
        """Devuelve la clave AES-256 como 32 bytes crudos."""
        try:
            crudo = base64.urlsafe_b64decode(_rellenar_base64(self.clave_cifrado_datos))
        except Exception as exc:  # pragma: no cover - error de configuracion
            raise ValueError("CLAVE_CIFRADO_DATOS no es base64 valido") from exc
        if len(crudo) != 32:
            raise ValueError(
                "CLAVE_CIFRADO_DATOS debe decodificar a exactamente 32 bytes (AES-256)"
            )
        return crudo

    def validar_para_produccion(self) -> None:
        """Falla ruidosamente si quedaron valores de desarrollo en produccion."""
        if not self.es_produccion:
            return
        problemas: list[str] = []
        for nombre, valor in (
            ("SECRET_KEY", self.secret_key),
            ("CLAVE_CIFRADO_DATOS", self.clave_cifrado_datos),
            ("CLAVE_INDICE_CIEGO", self.clave_indice_ciego),
        ):
            bajo = valor.lower()
            if any(p in bajo for p in PLACEHOLDERS_INSEGUROS) or "dev-" in bajo:
                problemas.append(f"{nombre} conserva un valor de ejemplo/desarrollo")
        if not self.cookie_segura:
            problemas.append("COOKIE_SEGURA debe ser true en produccion (HTTPS)")
        if self.debug:
            problemas.append("DEBUG debe ser false en produccion")
        if not self.lista_origenes:
            problemas.append("ORIGENES_PERMITIDOS no puede estar vacio en produccion")
        if problemas:
            raise RuntimeError("Configuracion insegura para produccion: " + "; ".join(problemas))


def _rellenar_base64(valor: str) -> str:
    """Agrega el padding '=' que falte para que base64 decodifique."""
    return valor + "=" * (-len(valor) % 4)


@lru_cache
def obtener_config() -> Config:
    config = Config()
    config.validar_para_produccion()
    return config
