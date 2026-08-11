"""Timestamps de interacciones y auditorias con clock_timestamp

now() devuelve la hora de inicio de la transacción: el mensaje del ciudadano y la
respuesta del agente, que se guardan juntos, quedaban con el mismo timestamp y el
panel los ordenaba de forma arbitraria. clock_timestamp() da la hora real de cada
INSERT.

Revision ID: d5c17a4b9e02
Revises: c91d40b2ae15
"""

from alembic import op

revision = "d5c17a4b9e02"
down_revision = "c91d40b2ae15"
branch_labels = None
depends_on = None

TABLAS = ("interacciones", "auditorias")


def upgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN timestamp SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ALTER COLUMN timestamp SET DEFAULT now()")
