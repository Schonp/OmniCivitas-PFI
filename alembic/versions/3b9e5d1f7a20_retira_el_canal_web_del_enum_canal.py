"""Retira el canal web del enum canal

El chat web propio sostuvo la demo mientras no estaban integrados Twilio e
IMAP/SMTP. Con los tres canales reales andando (WhatsApp, email y voz) se
retira: el código del canal ya no existe y el valor queda fuera del tipo.

Misma técnica que c6730a402335 (sms): Postgres no permite sacar un valor de
un enum con ALTER TYPE, así que se crea el tipo nuevo, se migran las columnas
y se borra el viejo. A diferencia de sms, web sí tuvo filas: si queda alguna
el cast fallaría a mitad de camino, así que se corta antes con un mensaje
claro en vez de inventarles otro canal.

Revision ID: 3b9e5d1f7a20
Revises: c6730a402335
"""

import sqlalchemy as sa
from alembic import op

revision = "3b9e5d1f7a20"
down_revision = "c6730a402335"
branch_labels = None
depends_on = None

VALORES_SIN_WEB = ("whatsapp", "email", "voz")
VALORES_CON_WEB = ("whatsapp", "email", "voz", "web")

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
    conexion = op.get_bind()
    for tabla, columna in COLUMNAS:
        filas = conexion.execute(
            sa.text(f"SELECT count(*) FROM {tabla} WHERE {columna} = 'web'")
        ).scalar()
        if filas:
            raise RuntimeError(
                f"Quedan {filas} fila(s) de {tabla}.{columna} con canal 'web'. "
                "Hay que borrarlas o reasignarlas antes de migrar."
            )
    _recrear_tipo(VALORES_SIN_WEB)


def downgrade() -> None:
    _recrear_tipo(VALORES_CON_WEB)
