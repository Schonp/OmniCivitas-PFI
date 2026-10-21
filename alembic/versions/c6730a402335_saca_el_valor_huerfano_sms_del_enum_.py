"""Saca el valor huérfano sms del enum canal

El tipo canal de Postgres se creó con 5 valores (whatsapp, sms, email, voz,
web) en la migración inicial, pero el enum Python de Canal nunca tuvo sms:
quedó huérfano desde el día cero, sin ninguna fila que lo use. Postgres no
permite sacar un valor de un enum con ALTER TYPE: hay que crear el tipo
nuevo sin ese valor, migrar las columnas que lo usan, y borrar el tipo viejo.

El valor web no se toca acá -- sigue en uso por app/channels/web.py y el
canal de chat interno, a diferencia de sms. Ver docstring de Canal en
app/db/models.py.

Revision ID: c6730a402335
Revises: f1a3c7d20b94
"""

import sqlalchemy as sa
from alembic import op

revision = "c6730a402335"
down_revision = "f1a3c7d20b94"
branch_labels = None
depends_on = None

VALORES_SIN_SMS = ("whatsapp", "email", "voz", "web")
VALORES_CON_SMS = ("whatsapp", "sms", "email", "voz", "web")

COLUMNAS = (("casos", "canal_origen"), ("casos", "canal_actual"), ("interacciones", "canal"))


def _recrear_tipo(valores: tuple[str, ...]) -> None:
    op.execute("ALTER TYPE canal RENAME TO canal_viejo")
    sa.Enum(*valores, name="canal").create(op.get_bind())
    for tabla, columna in COLUMNAS:
        op.execute(
            f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE canal USING {columna}::text::canal"
        )
    op.execute("DROP TYPE canal_viejo")


def upgrade() -> None:
    _recrear_tipo(VALORES_SIN_SMS)


def downgrade() -> None:
    _recrear_tipo(VALORES_CON_SMS)
