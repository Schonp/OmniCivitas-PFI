"""ciudadanos_hash_lookup

Columnas de hash determinístico (HMAC-SHA256) para poder buscar ciudadanos
por teléfono/email: Fernet es aleatorio y no permite lookup por igualdad.

Revision ID: c91d40b2ae15
Revises: a73ee79dc348
Create Date: 2026-07-28
"""

import sqlalchemy as sa

from alembic import op

revision = "c91d40b2ae15"
down_revision = "a73ee79dc348"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ciudadanos", sa.Column("email_hash", sa.String(length=64), nullable=True))
    op.add_column("ciudadanos", sa.Column("telefono_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_ciudadanos_email_hash", "ciudadanos", ["email_hash"])
    op.create_index("ix_ciudadanos_telefono_hash", "ciudadanos", ["telefono_hash"])

    # Backfill: desencripta los contactos existentes y calcula sus hashes.
    from app.core.security import decrypt_str, hash_lookup_str

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, email, telefono FROM ciudadanos")
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE ciudadanos SET email_hash = :eh, telefono_hash = :th WHERE id = :id"
            ),
            {
                "eh": hash_lookup_str(decrypt_str(row.email)) if row.email else None,
                "th": hash_lookup_str(decrypt_str(row.telefono)) if row.telefono else None,
                "id": row.id,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_ciudadanos_telefono_hash", table_name="ciudadanos")
    op.drop_index("ix_ciudadanos_email_hash", table_name="ciudadanos")
    op.drop_column("ciudadanos", "telefono_hash")
    op.drop_column("ciudadanos", "email_hash")
