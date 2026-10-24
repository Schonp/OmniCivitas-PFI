"""Aviso de que del otro lado hay una IA, no una persona.

El ciudadano tiene que saber con qué está hablando desde el primer mensaje. Se
antepone por código y no se le pide al modelo: un aviso de transparencia que
depende de que el LLM se acuerde de decirlo no es un aviso, es una intención.

El alcance es **la conversación del ciudadano en ese canal**, no el caso. Un
mismo intercambio por WhatsApp abre un caso nuevo cada vez que el ciudadano
cambia de tema, así que atarlo al caso hacía que el aviso saliera en casi todos
los mensajes. Se repite recién cuando pasaron horas sin hablar
(`agente_horas_aviso_ia`): ahí el ciudadano ya no tiene presente con qué está
hablando y el recordatorio vuelve a tener sentido.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ActorInteraccion, Canal, Caso, Interaccion

AVISO_IA = (
    "Le responde el asistente virtual del organismo, una inteligencia artificial. "
    "Si en algún momento prefiere hablar con una persona del equipo, pídamelo y lo derivo."
)

# RF-02: en el primer contacto, qué se guarda, para qué y cómo ejercer los
# derechos de la Ley 25.326. Una sola vez: repetirlo en cada conversación lo
# convierte en ruido que nadie lee.
AVISO_DATOS = (
    "Para gestionar su pedido el organismo guarda su número de teléfono o su correo, "
    "su nombre y DNI si los informa, y lo que cuente en esta conversación. Se usan solo "
    "para atenderlo. Puede pedir consultar, corregir o dar de baja sus datos cuando quiera, "
    "por este mismo medio."
)


async def ya_se_le_aviso(
    db: AsyncSession, ciudadano_id: uuid.UUID, canal: Canal
) -> bool:
    """¿El agente ya le habló por este canal dentro de la ventana del aviso?"""
    desde = datetime.now(timezone.utc) - timedelta(hours=settings.agente_horas_aviso_ia)
    consulta = (
        select(Interaccion.id)
        .join(Caso, Caso.id == Interaccion.caso_id)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Interaccion.actor == ActorInteraccion.agente_ia,
            Interaccion.interna.is_(False),
            Interaccion.canal == canal,
            Interaccion.timestamp >= desde,
        )
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first() is not None


async def es_primer_contacto(db: AsyncSession, ciudadano_id: uuid.UUID) -> bool:
    """¿El organismo nunca le respondió nada, por ningún canal?"""
    consulta = (
        select(Interaccion.id)
        .join(Caso, Caso.id == Interaccion.caso_id)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Interaccion.actor != ActorInteraccion.ciudadano,
            Interaccion.interna.is_(False),
        )
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first() is None


async def anteponer_aviso(
    db: AsyncSession, ciudadano_id: uuid.UUID, canal: Canal, texto: str
) -> str:
    """Devuelve el texto con el aviso adelante si corresponde avisarle ahora."""
    if not texto.strip():
        return texto
    if await ya_se_le_aviso(db, ciudadano_id, canal):
        return texto
    if await es_primer_contacto(db, ciudadano_id):
        return f"{AVISO_IA} {AVISO_DATOS}\n\n{texto}"
    return f"{AVISO_IA}\n\n{texto}"
