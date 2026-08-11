import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Reserva, Turno


async def listar_turnos_con_reservas(db: AsyncSession) -> list[Turno]:
    consulta = (
        select(Turno)
        .options(selectinload(Turno.reservas).selectinload(Reserva.ciudadano))
        .order_by(Turno.nombre)
    )
    return list((await db.execute(consulta)).scalars().all())


async def obtener_turno_por_nombre(db: AsyncSession, nombre: str) -> Turno | None:
    """Búsqueda tolerante: el LLM manda el nombre del turno como texto."""
    consulta = select(Turno).where(Turno.nombre.ilike(f"%{nombre.strip()}%")).limit(2)
    coincidencias = list((await db.execute(consulta)).scalars().all())
    # Con más de una coincidencia no hay forma segura de elegir.
    return coincidencias[0] if len(coincidencias) == 1 else None


async def listar_nombres_de_turnos(db: AsyncSession) -> list[str]:
    consulta = select(Turno.nombre).order_by(Turno.nombre)
    return list((await db.execute(consulta)).scalars().all())


async def crear_reserva_de_turno(
    db: AsyncSession,
    *,
    turno_id: uuid.UUID,
    caso_id: uuid.UUID,
    ciudadano_id: uuid.UUID,
    fecha_hora: datetime,
) -> Reserva:
    """Agrega la reserva a la transacción del caller. No hace commit."""
    reserva = Reserva(
        turno_id=turno_id, caso_id=caso_id, ciudadano_id=ciudadano_id, fecha_hora=fecha_hora
    )
    db.add(reserva)
    await db.flush()
    return reserva
