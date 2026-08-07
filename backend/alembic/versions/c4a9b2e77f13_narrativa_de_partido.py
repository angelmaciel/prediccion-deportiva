"""Narrativa de partido escrita por un modelo de lenguaje

Revision ID: c4a9b2e77f13
Revises: b3d5e8f21c47
Create Date: 2026-08-07

Se guarda el texto junto al modelo que lo escribio y las fuentes que cito, para
poder auditar de donde salio cada afirmacion sobre lesiones o convocatorias.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a9b2e77f13"
down_revision = "b3d5e8f21c47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrativas_partido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("partido_id", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("modelo", sa.String(length=60), nullable=False),
        sa.Column("fuentes", sa.JSON(), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_salida", sa.Integer(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["partido_id"], ["partidos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_narrativas_partido_partido_id", "narrativas_partido", ["partido_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_narrativas_partido_partido_id", table_name="narrativas_partido")
    op.drop_table("narrativas_partido")
