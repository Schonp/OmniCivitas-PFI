import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.db.crud.casos import obtener_caso_abierto_de_ciudadano
from app.db.crud.ciudadanos import (
    obtener_ciudadano_por_email,
    obtener_ciudadano_por_telefono,
)
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.models import Canal, Ciudadano

logger = logging.getLogger(__name__)

HISTORIAL_MAX_INTERACCIONES = 10


async def obtener_ciudadano_por_canal(
    db: AsyncSession, canal: Canal, identificador: str
) -> Ciudadano | None:
    if canal in (Canal.whatsapp, Canal.sms, Canal.voz):
        return await obtener_ciudadano_por_telefono(db, identificador)
    if canal == Canal.email:
        return await obtener_ciudadano_por_email(db, identificador)
    # Canal web: el identificador puede ser email o teléfono.
    ciudadano = await obtener_ciudadano_por_email(db, identificador)
    if ciudadano is None:
        ciudadano = await obtener_ciudadano_por_telefono(db, identificador)
    return ciudadano


async def buscar_conocimiento(intencion: str | None, mensaje: str) -> list[str]:
    """Stub RAG: la búsqueda semántica en pgvector (FAQs/trámites) se implementa
    en una fase posterior. La interfaz queda fija para no tocar el nodo."""
    return []


async def nodo_contexto(state: AgentState, db: AsyncSession) -> dict:
    ciudadano = await obtener_ciudadano_por_canal(
        db, Canal(state["canal"]), state["identificador"]
    )
    if ciudadano is None:
        logger.debug("contexto: ciudadano no identificado por canal %s", state["canal"])
        return {"ciudadano_id": None, "caso_id": None, "historial": [], "conocimiento": []}

    caso = await obtener_caso_abierto_de_ciudadano(db, ciudadano.id)
    historial: list[dict] = []
    if caso is not None:
        interacciones = await listar_interacciones_de_caso(
            db, caso.id, limite=HISTORIAL_MAX_INTERACCIONES
        )
        historial = [
            {"actor": i.actor.value, "contenido": i.contenido, "canal": i.canal.value}
            for i in interacciones
        ]

    conocimiento = await buscar_conocimiento(state.get("intencion"), state["mensaje"])

    return {
        "ciudadano_id": str(ciudadano.id),
        "caso_id": str(caso.id) if caso is not None else None,
        "historial": historial,
        "conocimiento": conocimiento,
    }
