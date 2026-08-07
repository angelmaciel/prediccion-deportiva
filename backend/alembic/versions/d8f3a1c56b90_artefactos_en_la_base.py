"""Artefactos del modelo guardados en la base

Revision ID: d8f3a1c56b90
Revises: c4a9b2e77f13
Create Date: 2026-08-07

En produccion el job que entrena y el servicio que predice corren en maquinas
distintas con discos efimeros. Un `.joblib` en disco no sobrevive al reinicio
del servicio ni cruza de una maquina a la otra; la base si.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8f3a1c56b90"
down_revision = "c4a9b2e77f13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versiones_modelo", sa.Column("artefacto_modelo", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "versiones_modelo", sa.Column("artefacto_poisson", sa.LargeBinary(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("versiones_modelo", "artefacto_poisson")
    op.drop_column("versiones_modelo", "artefacto_modelo")
