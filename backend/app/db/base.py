"""Clase base declarativa de SQLAlchemy y utilidades de tipos."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base comun de todos los modelos ORM."""


def enum_por_valor(clase: type[StrEnum], length: int) -> Enum:
    """Columna de enum que guarda el `.value`, no el nombre del miembro.

    Por defecto SQLAlchemy persiste el nombre (`VISITANTE`); guardar el valor
    (`V`) deja la base legible y consistente con lo que expone la API.
    `native_enum=False` la vuelve un VARCHAR con CHECK, portable entre
    PostgreSQL y SQLite (que se usa en los tests).
    """
    return Enum(
        clase,
        native_enum=False,
        length=length,
        values_callable=lambda miembros: [m.value for m in miembros],
    )
