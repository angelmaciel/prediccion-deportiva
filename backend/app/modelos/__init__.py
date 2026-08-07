"""Modelos ORM. Importar desde aca para que Alembic los vea todos."""

from app.modelos.auditoria import ConsumoCuota, EjecucionJob, LogAcceso
from app.modelos.futbol import (
    Equipo,
    EstadoPartido,
    FeaturesPartido,
    Fuente,
    Partido,
    RatingElo,
    Resultado,
)
from app.modelos.prediccion import MetricaJornada, Prediccion, VersionModelo
from app.modelos.usuarios import Rol, Sesion, Usuario

__all__ = [
    "ConsumoCuota",
    "Equipo",
    "EjecucionJob",
    "EstadoPartido",
    "FeaturesPartido",
    "Fuente",
    "LogAcceso",
    "MetricaJornada",
    "Partido",
    "Prediccion",
    "RatingElo",
    "Resultado",
    "Rol",
    "Sesion",
    "Usuario",
    "VersionModelo",
]
