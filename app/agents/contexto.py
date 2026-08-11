import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.db.crud.casos import obtener_caso_abierto_de_ciudadano
from app.db.crud.ciudadanos import (
    obtener_ciudadano_por_email,
    obtener_ciudadano_por_telefono,
)
from app.db.crud.conocimiento import buscar_documentos_relevantes
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.crud.turnos import listar_nombres_de_turnos
from app.db.models import Canal, Ciudadano

logger = logging.getLogger(__name__)

HISTORIAL_MAX_INTERACCIONES = 10


async def obtener_ciudadano_por_canal(
    db: AsyncSession, canal: Canal, identificador: str
) -> Ciudadano | None:
    if canal in (Canal.whatsapp, Canal.voz):
        return await obtener_ciudadano_por_telefono(db, identificador)
    if canal == Canal.email:
        return await obtener_ciudadano_por_email(db, identificador)
    # Canal web: el identificador puede ser email o teléfono.
    ciudadano = await obtener_ciudadano_por_email(db, identificador)
    if ciudadano is None:
        ciudadano = await obtener_ciudadano_por_telefono(db, identificador)
    return ciudadano


async def buscar_conocimiento(
    db: AsyncSession, intencion: str | None, mensaje: str
) -> list[str]:
    """Contexto del organismo para el ejecutor: documentos de la base de
    conocimiento que mencionan palabras del mensaje (recuperación léxica; la
    semántica con pgvector queda para una fase posterior) y, si la intención es
    reservar, las agendas de turnos disponibles para que la tool reciba un
    nombre válido."""
    conocimiento = await buscar_documentos_relevantes(db, mensaje)

    if intencion == "reserva":
        nombres = await listar_nombres_de_turnos(db)
        if nombres:
            conocimiento.append("Turnos disponibles para reservar: " + "; ".join(nombres))

    return conocimiento


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
        # Sin notas internas: si entraran al contexto, el LLM podría repetirle al
        # ciudadano algo que el organismo anotó para uso propio.
        interacciones = await listar_interacciones_de_caso(
            db, caso.id, limite=HISTORIAL_MAX_INTERACCIONES, incluir_internas=False
        )
        historial = [
            {"actor": i.actor.value, "contenido": i.contenido, "canal": i.canal.value}
            for i in interacciones
        ]

    conocimiento = await buscar_conocimiento(db, state.get("intencion"), state["mensaje"])

    return {
        "ciudadano_id": str(ciudadano.id),
        "caso_id": str(caso.id) if caso is not None else None,
        "historial": historial,
        "conocimiento": conocimiento,
    }
