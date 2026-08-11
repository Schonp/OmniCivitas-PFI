"""Turnos/reservas, base de conocimiento y grupos de reclamos IA

- `turnos` + `reservas`: agendas del organismo y las reservas que hace el agente,
  para poder verificar desde el panel que reserva bien.
- `documentos_conocimiento`: contexto que el organismo carga para la IA.
- `grupos_reclamos`: foto de la agrupación de reclamos afines hecha por la IA.

Revision ID: c9e42a7f18d3
Revises: b4d81f3a9c25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "c9e42a7f18d3"
down_revision = "b4d81f3a9c25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "turnos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(length=200), nullable=False, unique=True),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "reservas",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("turno_id", UUID(as_uuid=True), sa.ForeignKey("turnos.id"), nullable=False),
        sa.Column("caso_id", UUID(as_uuid=True), sa.ForeignKey("casos.id"), nullable=False),
        sa.Column(
            "ciudadano_id", UUID(as_uuid=True), sa.ForeignKey("ciudadanos.id"), nullable=False
        ),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_reservas_turno_id", "reservas", ["turno_id"])
    op.create_index("ix_reservas_caso_id", "reservas", ["caso_id"])
    op.create_index("ix_reservas_ciudadano_id", "reservas", ["ciudadano_id"])

    op.create_table(
        "documentos_conocimiento",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "grupos_reclamos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tema", sa.String(length=200), nullable=False),
        sa.Column("caso_ids", sa.JSON(), nullable=False),
        sa.Column(
            "generado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("grupos_reclamos")
    op.drop_table("documentos_conocimiento")
    op.drop_index("ix_reservas_ciudadano_id", table_name="reservas")
    op.drop_index("ix_reservas_caso_id", table_name="reservas")
    op.drop_index("ix_reservas_turno_id", table_name="reservas")
    op.drop_table("reservas")
    op.drop_table("turnos")
