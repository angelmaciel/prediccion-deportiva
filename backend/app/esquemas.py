"""Esquemas Pydantic: validacion estricta de entrada y forma de las respuestas.

Todo endpoint valida su entrada aca; ningun handler recibe datos crudos.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.seguridad import validar_fortaleza_password

# `extra="forbid"` hace que un campo no esperado sea un 422 en vez de ignorarse
# en silencio: superficie de ataque mas chica y errores mas visibles.
BASE = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Autenticacion ---


class RegistroEntrada(BaseModel):
    model_config = BASE

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def _fortaleza(cls, v: str) -> str:
        fallas = validar_fortaleza_password(v)
        if fallas:
            raise ValueError("La contrasena " + "; ".join(fallas))
        return v


class LoginEntrada(BaseModel):
    model_config = BASE

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)
    codigo_totp: str | None = Field(default=None, min_length=6, max_length=8, pattern=r"^\d{6,8}$")


class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    rol: str
    totp_activo: bool
    creado_en: datetime


class ProveedoresSalida(BaseModel):
    """Formas de ingreso habilitadas en este entorno."""

    google: bool


class MensajeSalida(BaseModel):
    mensaje: str


class TotpAltaSalida(BaseModel):
    secreto: str
    uri_provisioning: str
    mensaje: str = (
        "Escanear el codigo con la app de autenticacion y confirmar con un codigo valido."
    )


class TotpConfirmacionEntrada(BaseModel):
    model_config = BASE

    codigo: str = Field(min_length=6, max_length=8, pattern=r"^\d{6,8}$")


# --- Futbol ---


class EquipoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    nombre_corto: str | None = None
    liga: str
    pais: str
    escudo_url: str | None = None


class PrediccionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prob_local: float
    prob_empate: float
    prob_visitante: float
    marcador_probable_local: int | None = None
    marcador_probable_visitante: int | None = None
    modelo_version: str
    resultado_predicho: str
    confianza: float
    creado_en: datetime


class PartidoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: datetime
    liga: str
    temporada: str | None = None
    jornada: int | None = None
    estado: str
    equipo_local: EquipoSalida
    equipo_visitante: EquipoSalida
    goles_local: int | None = None
    goles_visitante: int | None = None
    resultado_real: str | None = None
    prediccion: PrediccionSalida | None = None


class PaginaPartidos(BaseModel):
    total: int
    pagina: int
    por_pagina: int
    items: list[PartidoSalida]


# --- Transparencia / metricas ---


class MetricaJornadaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    liga: str
    temporada: str | None = None
    jornada: int | None = None
    modelo_version: str
    partidos_evaluados: int
    aciertos: int
    accuracy: float
    brier: float | None = None


class ResumenModeloSalida(BaseModel):
    version_activa: str | None
    algoritmo: str | None
    entrenado_en: datetime | None
    partidos_entrenamiento: int
    accuracy_walk_forward: float | None
    log_loss: float | None
    brier: float | None
    partidos_evaluados: int
    aciertos: int
    accuracy_real: float
    linea_base_local: float
    aviso: str = (
        "Las probabilidades son estimaciones estadisticas basadas en datos historicos, "
        "no garantias de resultado."
    )


class PliegueSalida(BaseModel):
    pliegue: int
    n_entrenamiento: int
    n_evaluacion: int
    accuracy: float
    log_loss: float
    brier: float


class VersionModeloSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: str
    algoritmo: str
    entrenado_en: datetime
    partidos_entrenamiento: int
    accuracy: float | None = None
    log_loss: float | None = None
    brier: float | None = None
    activa: bool


# --- Admin ---


class ConsumoCuotaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fuente: str
    dia: object
    requests: int
    errores: int
    limite_diario: int | None = None


class EjecucionJobSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: str
    inicio: datetime
    fin: datetime | None = None
    exito: bool
    registros_afectados: int
    mensaje: str | None = None


class LogAccesoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int | None = None
    accion: str
    exito: bool
    ip: str | None = None
    detalle: str | None = None
    timestamp: datetime


class EntrenamientoEntrada(BaseModel):
    model_config = BASE

    algoritmo: str = Field(default="logistica", pattern=r"^(logistica|random_forest)$")


class ResumenEntrenamientoSalida(BaseModel):
    version: str
    algoritmo: str
    partidos_entrenamiento: int
    accuracy: float
    log_loss: float
    brier: float
    linea_base: float
    pliegues: list[PliegueSalida]


# --- Historial de enfrentamientos directos ---

AVISO_ATAJADAS = (
    "Las atajadas son una estimacion: la fuente no las publica y se calculan "
    "como remates al arco del rival menos goles recibidos."
)


class PromediosH2H(BaseModel):
    """Promedios por partido. `null` = la fuente no trae ese dato."""

    goles_favor: float | None = None
    goles_contra: float | None = None
    remates: float | None = None
    remates_arco: float | None = None
    corners: float | None = None
    faltas: float | None = None
    amarillas: float | None = None
    rojas: float | None = None
    atajadas: float | None = None


class EquipoH2H(BaseModel):
    equipo_id: int
    nombre: str
    jugados: int
    ganados: int
    empatados: int
    perdidos: int
    promedios: PromediosH2H


class CruceH2H(BaseModel):
    partido_id: int
    fecha: datetime
    liga: str
    temporada: str | None = None
    local: str
    visitante: str
    goles_local: int
    goles_visitante: int
    tiene_estadisticas: bool


class HistorialH2H(BaseModel):
    partido_id: int
    solo_misma_localia: bool
    liga: str | None = None
    total_cruces: int
    cruces_con_estadisticas: int
    local: EquipoH2H
    visitante: EquipoH2H
    cruces: list[CruceH2H]
    aviso_atajadas: str = AVISO_ATAJADAS
