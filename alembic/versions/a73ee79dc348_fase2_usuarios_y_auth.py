"""fase2_usuarios_y_auth

Revision ID: a73ee79dc348
Revises: fe6c2a888a63
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a73ee79dc348"
down_revision = "fe6c2a888a63"
branch_labels = None
depends_on = None

rol_usuario = postgresql.ENUM("operador", "supervisor", "admin", name="rol_usuario", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    rol_usuario.create(bind, checkfirst=True)

    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("rol", rol_usuario, nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"], unique=True)

    op.create_foreign_key(
        "fk_casos_operador_asignado_id_usuarios",
        "casos",
        "usuarios",
        ["operador_asignado_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_casos_operador_asignado_id_usuarios", "casos", type_="foreignkey")
    op.drop_table("usuarios")

    bind = op.get_bind()
    rol_usuario.drop(bind, checkfirst=True)
