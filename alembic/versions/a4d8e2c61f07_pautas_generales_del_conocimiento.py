"""Pautas generales en la base de conocimiento

Un documento marcado como general es una pauta de comportamiento del agente:
entra al prompt del ejecutor en todas las conversaciones, en vez de
recuperarse solo cuando el mensaje del ciudadano lo menciona. Los documentos
existentes quedan como no generales, que es como se venían usando.

Revision ID: a4d8e2c61f07
Revises: 3b9e5d1f7a20
"""

import sqlalchemy as sa
from alembic import op

revision = "a4d8e2c61f07"
down_revision = "3b9e5d1f7a20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documentos_conocimiento",
        sa.Column("general", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("documentos_conocimiento", "general")
