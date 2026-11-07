"""Título del caso

Con qué se nombra el caso cuando se le ofrece al ciudadano retomarlo ("uno,
reclamo por pozo en Guatemala 4100"). Lo completa el agente al registrar el
reclamo o el turno, y el supervisor lo puede corregir desde el panel.

Revision ID: d2a9b4e7c81f
Revises: c3f8a2d6e915
"""

import sqlalchemy as sa
from alembic import op

revision = "d2a9b4e7c81f"
down_revision = "c3f8a2d6e915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("casos", sa.Column("titulo", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("casos", "titulo")
