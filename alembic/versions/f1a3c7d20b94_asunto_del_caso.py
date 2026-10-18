"""Asunto del correo que abrió el caso

Sin esto, la respuesta del operador salía con un asunto genérico y en la bandeja
del ciudadano aparecía como un mensaje suelto en vez de continuar su consulta.

Revision ID: f1a3c7d20b94
Revises: c9e42a7f18d3
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a3c7d20b94"
down_revision = "c9e42a7f18d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("casos", sa.Column("asunto", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("casos", "asunto")
