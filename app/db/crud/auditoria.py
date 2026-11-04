import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActorInteraccion, Auditoria


async def registrar_auditoria(
    db: AsyncSession,
    *,
    caso_id: uuid.UUID,
    accion: str,
    actor: str,
    actor_tipo: ActorInteraccion,
    metadata: dict[str, Any] | None = None,
) -> Auditoria:
    """Registra una entrada de auditoría en la misma transacción del caller.

    No hace commit: el caller decide cuándo confirmar, para que el cambio
    sobre el Caso y su auditoría queden atómicos en una sola transacción.
    """
    entrada = Auditoria(
        caso_id=caso_id,
        accion=accion,
        actor=actor,
        actor_tipo=actor_tipo,
        metadata_=metadata,
    )
    db.add(entrada)
    await db.flush()
    return entrada


async def listar_auditoria_de_caso(db: AsyncSession, caso_id: uuid.UUID) -> list[Auditoria]:
    resultado = await db.execute(
        select(Auditoria).where(Auditoria.caso_id == caso_id).order_by(Auditoria.timestamp)
    )
    return list(resultado.scalars().all())


async def eventos_desde(
    db: AsyncSession, acciones: tuple[str, ...], desde: datetime
) -> list[Auditoria]:
    """Las entradas con esas acciones posteriores a `desde`, de la más vieja a la más nueva."""
    resultado = await db.execute(
        select(Auditoria)
        .where(Auditoria.accion.in_(acciones), Auditoria.timestamp > desde)
        .order_by(Auditoria.timestamp)
    )
    return list(resultado.scalars().all())
