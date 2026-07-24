"""fase1_modelos_iniciales

Revision ID: fe6c2a888a63
Revises:
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "fe6c2a888a63"
down_revision = None
branch_labels = None
depends_on = None

tipo_caso = postgresql.ENUM(
    "consulta", "reclamo", "reserva", "tramite", name="tipo_caso", create_type=False
)
estado_caso = postgresql.ENUM(
    "abierto", "en_progreso", "escalado", "cerrado", name="estado_caso", create_type=False
)
canal = postgresql.ENUM(
    "whatsapp", "sms", "email", "voz", "web", name="canal", create_type=False
)
actor_interaccion = postgresql.ENUM(
    "ciudadano", "agente_ia", "operador", name="actor_interaccion", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    tipo_caso.create(bind, checkfirst=True)
    estado_caso.create(bind, checkfirst=True)
    canal.create(bind, checkfirst=True)
    actor_interaccion.create(bind, checkfirst=True)

    op.create_table(
        "ciudadanos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("documento", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=500), nullable=True),
        sa.Column("telefono", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ciudadanos_documento", "ciudadanos", ["documento"], unique=True)

    op.create_table(
        "casos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ciudadano_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ciudadanos.id"),
            nullable=False,
        ),
        sa.Column("tipo", tipo_caso, nullable=False),
        sa.Column("estado", estado_caso, nullable=False),
        sa.Column("canal_origen", canal, nullable=False),
        sa.Column("canal_actual", canal, nullable=False),
        sa.Column("operador_asignado_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_casos_ciudadano_id", "casos", ["ciudadano_id"])

    op.create_table(
        "interacciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("caso_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("casos.id"), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("canal", canal, nullable=False),
        sa.Column("actor", actor_interaccion, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_interacciones_caso_id", "interacciones", ["caso_id"])

    op.create_table(
        "auditorias",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("caso_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("casos.id"), nullable=False),
        sa.Column("accion", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("actor_tipo", actor_interaccion, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.create_index("ix_auditorias_caso_id", "auditorias", ["caso_id"])


def downgrade() -> None:
    op.drop_table("auditorias")
    op.drop_table("interacciones")
    op.drop_table("casos")
    op.drop_table("ciudadanos")

    bind = op.get_bind()
    actor_interaccion.drop(bind, checkfirst=True)
    canal.drop(bind, checkfirst=True)
    estado_caso.drop(bind, checkfirst=True)
    tipo_caso.drop(bind, checkfirst=True)
