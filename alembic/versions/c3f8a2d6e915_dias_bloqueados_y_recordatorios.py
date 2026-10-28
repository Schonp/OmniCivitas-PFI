"""Días bloqueados en las agendas y recordatorio de turno

Un feriado o una jornada sin atención no se podía expresar: la grilla ofrecía
igual esos horarios. Y para recordarle el turno al ciudadano el día anterior
hace falta saber a quién ya se le mandó.

Revision ID: c3f8a2d6e915
Revises: b7e3f1a9c2d4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3f8a2d6e915"
down_revision = "b7e3f1a9c2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dias_bloqueados",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("turno_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("turnos.id", ondelete="CASCADE"), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("motivo", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dias_bloqueados_turno_id", "dias_bloqueados", ["turno_id"])
    op.create_index("ix_dias_bloqueados_fecha", "dias_bloqueados", ["fecha"])
    op.add_column("reservas", sa.Column("recordatorio_enviado_en", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reservas", "recordatorio_enviado_en")
    op.drop_index("ix_dias_bloqueados_fecha", table_name="dias_bloqueados")
    op.drop_index("ix_dias_bloqueados_turno_id", table_name="dias_bloqueados")
    op.drop_table("dias_bloqueados")
