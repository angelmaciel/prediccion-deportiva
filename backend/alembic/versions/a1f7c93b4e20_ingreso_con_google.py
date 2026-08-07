"""Ingreso con Google: proveedor, sub y contrasena opcional

Revision ID: a1f7c93b4e20
Revises: 22d28227017e
Create Date: 2026-08-07

Las cuentas creadas con Google no tienen contrasena, asi que `password_hash`
pasa a admitir nulos. `proveedor_sub` guarda el identificador estable de Google
(`sub`), que a diferencia del email no cambia nunca.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1f7c93b4e20"
down_revision = "22d28227017e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column(
            "proveedor",
            sa.String(length=20),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column("usuarios", sa.Column("proveedor_sub", sa.String(length=64), nullable=True))
    op.create_index("ix_usuarios_proveedor_sub", "usuarios", ["proveedor_sub"], unique=True)
    op.alter_column("usuarios", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Las cuentas sin contrasena no pueden sobrevivir a la vuelta atras.
    op.execute("DELETE FROM usuarios WHERE password_hash IS NULL")
    op.alter_column(
        "usuarios", "password_hash", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_index("ix_usuarios_proveedor_sub", table_name="usuarios")
    op.drop_column("usuarios", "proveedor_sub")
    op.drop_column("usuarios", "proveedor")
