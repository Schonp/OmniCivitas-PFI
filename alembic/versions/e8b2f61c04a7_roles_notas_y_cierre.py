"""Dos roles (operador/supervisor), notas internas y motivo de cierre

- El rol `admin` se funde en `supervisor`: el prototipo tiene dos roles funcionales.
  Postgres no permite quitar un valor de un enum, hay que rehacer el tipo.
- `interacciones.interna` distingue la nota que solo ve el organismo de la
  respuesta que llega al ciudadano.
- `casos.motivo_cierre` tipifica por qué se cerró un caso.

Revision ID: e8b2f61c04a7
Revises: d5c17a4b9e02
"""

import sqlalchemy as sa
from alembic import op

revision = "e8b2f61c04a7"
down_revision = "d5c17a4b9e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interacciones",
        sa.Column("interna", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("casos", sa.Column("motivo_cierre", sa.String(length=50), nullable=True))

    op.execute("UPDATE usuarios SET rol = 'supervisor' WHERE rol = 'admin'")
    op.execute("ALTER TYPE rol_usuario RENAME TO rol_usuario_anterior")
    op.execute("CREATE TYPE rol_usuario AS ENUM ('operador', 'supervisor')")
    op.execute(
        "ALTER TABLE usuarios ALTER COLUMN rol TYPE rol_usuario "
        "USING rol::text::rol_usuario"
    )
    op.execute("DROP TYPE rol_usuario_anterior")


def downgrade() -> None:
    op.execute("ALTER TYPE rol_usuario RENAME TO rol_usuario_anterior")
    op.execute("CREATE TYPE rol_usuario AS ENUM ('operador', 'supervisor', 'admin')")
    op.execute(
        "ALTER TABLE usuarios ALTER COLUMN rol TYPE rol_usuario "
        "USING rol::text::rol_usuario"
    )
    op.execute("DROP TYPE rol_usuario_anterior")

    op.drop_column("casos", "motivo_cierre")
    op.drop_column("interacciones", "interna")
