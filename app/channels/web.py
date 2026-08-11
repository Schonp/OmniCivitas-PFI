"""Canal web: chat propio del prototipo, sin dependencias externas.

Cumple el mismo contrato que cumplirán WhatsApp/email/voz: normaliza al ciudadano
y su identificador de canal, delega en el orquestador y devuelve la respuesta.
Toda la continuidad (caso abierto, historial, thread del checkpointer) la resuelve
el grafo a partir de `canal + identificador`.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import procesar_mensaje
from app.agents.state import AgentState
from app.db.crud.casos import obtener_caso_abierto_de_ciudadano
from app.db.crud.ciudadanos import crear_ciudadano, obtener_ciudadano_por_documento
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.models import Canal, Caso, Ciudadano, Interaccion
from app.schemas.chat import InicioSesionChat
from app.schemas.ciudadano import CiudadanoCreate

logger = logging.getLogger(__name__)

CANAL = Canal.web
HISTORIAL_MAX_INTERACCIONES = 50


async def identificar_ciudadano(db: AsyncSession, datos: InicioSesionChat) -> Ciudadano:
    """Busca por documento y, si es el primer contacto, da de alta al ciudadano.
    Si aportó un contacto nuevo, lo actualiza para poder alcanzarlo por ese medio."""
    ciudadano = await obtener_ciudadano_por_documento(db, datos.documento)
    if ciudadano is None:
        return await crear_ciudadano(
            db,
            CiudadanoCreate(
                documento=datos.documento,
                nombre=datos.nombre,
                email=datos.email,
                telefono=datos.telefono,
            ),
        )

    if datos.email and datos.email != ciudadano.email:
        ciudadano.email = datos.email
    if datos.telefono and datos.telefono != ciudadano.telefono:
        ciudadano.telefono = datos.telefono
    await db.commit()
    await db.refresh(ciudadano)
    return ciudadano


def identificador_de(ciudadano: Ciudadano) -> str:
    """Identificador del canal web: el contacto del ciudadano, igual que el número
    en WhatsApp. `contexto.obtener_ciudadano_por_canal` lo resuelve por email o
    teléfono, así el mismo caso continúa aunque cambie de canal."""
    identificador = ciudadano.email or ciudadano.telefono
    if identificador is None:
        raise ValueError("El ciudadano no tiene email ni teléfono registrado")
    return identificador


async def recibir_mensaje(
    db: AsyncSession, *, ciudadano: Ciudadano, mensaje: str
) -> AgentState:
    logger.debug("canal web: mensaje entrante de ciudadano=%s", ciudadano.id)
    return await procesar_mensaje(
        db,
        mensaje=mensaje,
        canal=CANAL,
        identificador=identificador_de(ciudadano),
    )


async def obtener_conversacion(
    db: AsyncSession, ciudadano: Ciudadano
) -> tuple[Caso | None, list[Interaccion]]:
    """Caso abierto del ciudadano con sus interacciones de todos los canales."""
    caso = await obtener_caso_abierto_de_ciudadano(db, ciudadano.id)
    if caso is None:
        return None, []
    interacciones = await listar_interacciones_de_caso(
        db, caso.id, limite=HISTORIAL_MAX_INTERACCIONES, incluir_internas=False
    )
    return caso, interacciones
