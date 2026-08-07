"""Estadisticas de partido (remates, corners, faltas, tarjetas)

Revision ID: b3d5e8f21c47
Revises: a1f7c93b4e20
Create Date: 2026-08-07

Todas las columnas admiten nulos a proposito: solo los partidos importados de
football-data.co.uk tienen estos datos. Nulo significa "no lo sabemos", que no
es lo mismo que cero.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3d5e8f21c47"
down_revision = "a1f7c93b4e20"
branch_labels = None
depends_on = None

COLUMNAS = (
    "remates",
    "remates_arco",
    "corners",
    "faltas",
    "amarillas",
    "rojas",
)


def upgrade() -> None:
    op.create_table(
        "estadisticas_partido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("partido_id", sa.Integer(), nullable=False),
        *[
            sa.Column(f"{nombre}_{lado}", sa.Integer(), nullable=True)
            for nombre in COLUMNAS
            for lado in ("local", "visitante")
        ],
        sa.ForeignKeyConstraint(["partido_id"], ["partidos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_estadisticas_partido_partido_id",
        "estadisticas_partido",
        ["partido_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_estadisticas_partido_partido_id", table_name="estadisticas_partido")
    op.drop_table("estadisticas_partido")
