import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_lookup_str
from app.db.models import Caso, Ciudadano, Reserva
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


async def alta_por_contacto(db: AsyncSession, datos: CiudadanoCreate) -> Ciudadano:
    """Alta del primer contacto por un canal, con el documento provisorio.

    Si ya hay un registro con ese mismo documento provisorio (quedó sin el
    contacto, por ejemplo después de unir registros), se le vuelve a asignar el
    contacto en vez de crear otro. Crearlo choca con el índice único del
    documento, y el canal quedaba devolviendo error en cada mensaje: así pasó
    con WhatsApp, que dejó de contestar."""
    existente = await obtener_ciudadano_por_documento(db, datos.documento)
    if existente is None:
        return await crear_ciudadano(db, datos)
    if datos.telefono:
        existente.telefono = datos.telefono
    if datos.email:
        existente.email = datos.email
    await db.commit()
    await db.refresh(existente)
    return existente


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
        # El contacto por el que está escribiendo ahora pasa a la persona, aunque
        # ya tuviera otro: es por donde se lo puede encontrar y responder. Antes
        # se descartaba si la persona ya tenía uno, y el vecino quedaba sin
        # registro alcanzable por su propio número.
        email, telefono = ciudadano.email, ciudadano.telefono
        ciudadano.email = None
        ciudadano.telefono = None
        await db.flush()
        if email:
            existente.email = email
        if telefono:
            existente.telefono = telefono
        # Lo que hizo antes de identificarse (el caso del primer contacto, un
        # turno) es suyo: si queda en el registro provisorio, nadie lo encuentra.
        for modelo in (Caso, Reserva):
            await db.execute(
                update(modelo).where(modelo.ciudadano_id == ciudadano.id).values(ciudadano_id=existente.id)
            )
        # Y el registro provisorio se borra: si quedaba vacío, su documento
        # provisorio seguía ocupado y el próximo primer contacto desde ese
        # número chocaba con él.
        await db.delete(ciudadano)
        await db.flush()
        return existente

    ciudadano.documento = documento
    ciudadano.nombre = nombre
    await db.flush()
    return ciudadano
