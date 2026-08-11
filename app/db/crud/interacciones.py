import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActorInteraccion, Canal, Interaccion


async def crear_interaccion(
    db: AsyncSession,
    *,
    caso_id: uuid.UUID,
    contenido: str,
    canal: Canal,
    actor: ActorInteraccion,
    interna: bool = False,
) -> Interaccion:
    """Agrega la interacción a la transacción del caller. No hace commit."""
    interaccion = Interaccion(
        caso_id=caso_id, contenido=contenido, canal=canal, actor=actor, interna=interna
    )
    db.add(interaccion)
    await db.flush()
    return interaccion


async def listar_interacciones_de_caso(
    db: AsyncSession, caso_id: uuid.UUID, *, limite: int = 10, incluir_internas: bool = True
) -> list[Interaccion]:
    """Últimas N interacciones del caso, en orden cronológico.

    `incluir_internas=False` para todo lo que ve el ciudadano: las notas del
    organismo nunca salen por un canal.
    """
    consulta = select(Interaccion).where(Interaccion.caso_id == caso_id)
    if not incluir_internas:
        consulta = consulta.where(Interaccion.interna.is_(False))

    resultado = await db.execute(
        consulta.order_by(Interaccion.timestamp.desc()).limit(limite)
    )
    return list(reversed(resultado.scalars().all()))
