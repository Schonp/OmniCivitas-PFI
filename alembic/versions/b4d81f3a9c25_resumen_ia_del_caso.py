"""Resumen del caso generado por IA

`casos.resumen_ia` guarda el resumen para el operador y
`casos.resumen_ia_generado_en` permite saber si quedó desactualizado
respecto de la conversación.

Revision ID: b4d81f3a9c25
Revises: e8b2f61c04a7
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d81f3a9c25"
down_revision = "e8b2f61c04a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("casos", sa.Column("resumen_ia", sa.Text(), nullable=True))
    op.add_column(
        "casos",
        sa.Column("resumen_ia_generado_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("casos", "resumen_ia_generado_en")
    op.drop_column("casos", "resumen_ia")
