"""Agenda de turnos con grilla, cupos y estado de la reserva

Hasta acá una agenda era solo un nombre y una reserva, cualquier fecha: se
podía reservar dos veces el mismo horario, un domingo o en el pasado, y no
había forma de cancelar. La agenda pasa a tener días y horario de atención,
duración de cada turno, cupos por horario y anticipación máxima; la reserva,
un estado (solo la confirmada ocupa cupo) y los datos de su cancelación.

Las reservas existentes quedan confirmadas, que es lo que eran.

Revision ID: b7e3f1a9c2d4
Revises: a4d8e2c61f07
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e3f1a9c2d4"
down_revision = "a4d8e2c61f07"
branch_labels = None
depends_on = None

ESTADO_RESERVA = sa.Enum("confirmada", "cancelada", "atendida", "ausente", name="estado_reserva")


def upgrade() -> None:
    op.add_column("turnos", sa.Column("sede", sa.String(length=200), nullable=True))
    op.add_column("turnos", sa.Column("dias_atencion", sa.String(length=20), nullable=False, server_default="0,1,2,3,4"))
    op.add_column("turnos", sa.Column("hora_apertura", sa.Time(), nullable=False, server_default="08:00"))
    op.add_column("turnos", sa.Column("hora_cierre", sa.Time(), nullable=False, server_default="14:00"))
    op.add_column("turnos", sa.Column("duracion_minutos", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("turnos", sa.Column("cupos_por_horario", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("turnos", sa.Column("anticipacion_maxima_dias", sa.Integer(), nullable=False, server_default="30"))

    ESTADO_RESERVA.create(op.get_bind(), checkfirst=True)
    op.add_column("reservas", sa.Column("estado", ESTADO_RESERVA, nullable=False, server_default="confirmada"))
    op.add_column("reservas", sa.Column("motivo_cancelacion", sa.String(length=300), nullable=True))
    op.add_column("reservas", sa.Column("cancelada_en", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ux_reserva_ciudadano_horario",
        "reservas",
        ["ciudadano_id", "fecha_hora"],
        unique=True,
        postgresql_where=sa.text("estado = 'confirmada'"),
    )


def downgrade() -> None:
    op.drop_index("ux_reserva_ciudadano_horario", table_name="reservas")
    op.drop_column("reservas", "cancelada_en")
    op.drop_column("reservas", "motivo_cancelacion")
    op.drop_column("reservas", "estado")
    ESTADO_RESERVA.drop(op.get_bind(), checkfirst=True)
    for columna in (
        "anticipacion_maxima_dias",
        "cupos_por_horario",
        "duracion_minutos",
        "hora_cierre",
        "hora_apertura",
        "dias_atencion",
        "sede",
    ):
        op.drop_column("turnos", columna)
