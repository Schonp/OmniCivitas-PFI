import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_lookup_str
from app.db.models import Caso, Ciudadano
from app.schemas.ciudadano import CiudadanoCreate

# `ciudadanos.documento` es obligatorio y unico, pero en el primer contacto por
# un canal externo solo conocemos el telefono o el correo. Se da de alta con un
# marcador derivado del hash del contacto: no colisiona, entra en String(20) y
# deja explicito que el ciudadano todavia no se identifico.
PREFIJO_DOCUMENTO_PROVISORIO = "SIN-DNI-"


def documento_provisorio(contacto: str) -> str:
    return f"{PREFIJO_DOCUMENTO_PROVISORIO}{hash_lookup_str(contacto)[:10]}"


def esta_identificado(ciudadano: Ciudadano) -> bool:
    """False mientras el ciudadano arrastre el documento provisorio del alta."""
    return not ciudadano.documento.startswith(PREFIJO_DOCUMENTO_PROVISORIO)


async def obtener_ciudadano_por_id(db: AsyncSession, ciudadano_id: uuid.UUID) -> Ciudadano | None:
    return await db.get(Ciudadano, ciudadano_id)


async def obtener_ciudadano_por_documento(db: AsyncSession, documento: str) -> Ciudadano | None:
    stmt = select(Ciudadano).where(Ciudadano.documento == documento)
    return (await db.execute(stmt)).scalars().first()


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


async def identificar_ciudadano(
    db: AsyncSession, ciudadano_id: uuid.UUID, *, documento: str, nombre: str
) -> Ciudadano:
    """Reemplaza el documento provisorio por el real que informó el ciudadano.

    Si ese documento ya existe en el padrón, el contacto del canal se suma a
    esa persona y el registro provisorio se descarta: es el mismo vecino
    escribiendo desde un medio nuevo, no uno distinto.
    """
    ciudadano = await db.get(Ciudadano, ciudadano_id)
    if ciudadano is None:
        raise ValueError("Ciudadano no encontrado")

    existente = await obtener_ciudadano_por_documento(db, documento)
    if existente is not None and existente.id != ciudadano.id:
        if ciudadano.email and not existente.email:
            existente.email = ciudadano.email
        if ciudadano.telefono and not existente.telefono:
            existente.telefono = ciudadano.telefono
        # El registro provisorio deja de ser alcanzable por esos contactos: si
        # no, dos ciudadanos comparten el mismo hash y la búsqueda por canal se
        # vuelve ambigua.
        ciudadano.email = None
        ciudadano.telefono = None
        # Lo que escribió antes de identificarse (el caso que se abrió en el
        # primer contacto) es suyo: si queda en el registro provisorio, que ya
        # no es alcanzable por ningún canal, nadie vuelve a encontrarlo.
        await db.execute(
            update(Caso).where(Caso.ciudadano_id == ciudadano.id).values(ciudadano_id=existente.id)
        )
        await db.flush()
        return existente

    ciudadano.documento = documento
    ciudadano.nombre = nombre
    await db.flush()
    return ciudadano
