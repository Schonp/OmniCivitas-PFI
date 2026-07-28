import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_lookup_str
from app.db.models import Ciudadano
from app.schemas.ciudadano import CiudadanoCreate


async def obtener_ciudadano_por_id(db: AsyncSession, ciudadano_id: uuid.UUID) -> Ciudadano | None:
    return await db.get(Ciudadano, ciudadano_id)


async def obtener_ciudadano_por_telefono(db: AsyncSession, telefono: str) -> Ciudadano | None:
    stmt = select(Ciudadano).where(Ciudadano.telefono_hash == hash_lookup_str(telefono))
    return (await db.execute(stmt)).scalars().first()


async def obtener_ciudadano_por_email(db: AsyncSession, email: str) -> Ciudadano | None:
    stmt = select(Ciudadano).where(Ciudadano.email_hash == hash_lookup_str(email))
    return (await db.execute(stmt)).scalars().first()


async def crear_ciudadano(db: AsyncSession, datos: CiudadanoCreate) -> Ciudadano:
    ciudadano = Ciudadano(
        documento=datos.documento,
        nombre=datos.nombre,
        email=datos.email,
        telefono=datos.telefono,
    )
    db.add(ciudadano)
    await db.commit()
    await db.refresh(ciudadano)
    return ciudadano
