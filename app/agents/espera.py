"""Nodo de espera: el caso ya está en manos de una persona.

Cuando el agente deriva un caso le dice al ciudadano que lo van a contactar,
pero el ciudadano igual escribe: aporta el dato que le faltaba, pregunta cómo
viene, insiste. Ese mensaje pertenece al caso derivado, y el agente no tiene
que retomarlo: no puede resolver lo que ya se decidió que resuelve un humano,
y si contestara pisaría el `resumen_ia` que el operador tiene para retomar y
sacaría el caso de la cola de "esperando respuesta".

Ahora bien, contestar siempre tampoco sirve. Si al ciudadano se le acaba de
decir que lo van a contactar, repetírselo cada vez que escribe es peor que el
silencio: parece un robot trabado. Por eso el agente se calla mientras lo
último que salió del organismo sea reciente (`agente_minutos_silencio_derivado`)
y solo acusa recibo cuando ya pasó un rato — ahí el ciudadano puede estar
pensando que su mensaje se perdió. El mensaje se registra en el caso en los dos
casos: lo que nunca puede pasar es que desaparezca.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.core.config import settings
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import ultimo_saliente_con_canal
from app.db.models import ActorInteraccion, Caso
from app.tools import ACTOR_AGENTE

logger = logging.getLogger(__name__)

ACUSE = (
    "Recibimos su mensaje y lo sumamos a su pedido{referencia}.\n\n"
    "Ya está en manos de una persona del equipo, que lo va a contactar por "
    "este mismo medio dentro del horario de atención."
)


def mensaje_espera(referencia: str | None = None) -> str:
    return ACUSE.format(referencia=f" {referencia}" if referencia else "")


def contacto_reciente(ultimo_saliente: datetime | None) -> bool:
    """True si el organismo le escribió hace poco.

    Marca dos cosas con el mismo umbral, y a propósito: que el agente no repita
    el acuse de recibo, y que una cortesía se lea como parte del hilo y no como
    el arranque de una conversación nueva. Son la misma pregunta —"¿esto sigue
    siendo la misma conversación?"— y tenerlas atadas evita que se contradigan.
    """
    if ultimo_saliente is None:
        return False
    if ultimo_saliente.tzinfo is None:
        ultimo_saliente = ultimo_saliente.replace(tzinfo=timezone.utc)
    ventana = timedelta(minutes=settings.agente_minutos_silencio_derivado)
    return datetime.now(timezone.utc) - ultimo_saliente < ventana


async def _ya_le_avisaron_por_este_canal(
    db: AsyncSession, caso_id: uuid.UUID, canal: str | None
) -> bool:
    """True si el agente puede callarse: lo último que le dijo el organismo es
    reciente y salió por el mismo canal por el que ahora escribe.

    El canal importa porque el silencio solo se entiende si el ciudadano vio el
    aviso. Pasó en una demo: pidió una persona por teléfono, la llamada le dijo
    que lo iban a contactar, y a los pocos minutos escribió "hola" por WhatsApp.
    Ahí lo último que había visto era la confirmación del reclamo, y el chat
    quedó mudo durante la media hora de la ventana. Con otro canal se acusa
    recibo una vez; ese acuse ya sale por el canal nuevo, así que lo que siga
    por ahí vuelve a respetar la ventana.
    """
    ultimo = await ultimo_saliente_con_canal(db, caso_id)
    if ultimo is None:
        return False
    momento, canal_del_aviso = ultimo
    return canal_del_aviso.value == canal and contacto_reciente(momento)


async def nodo_espera(state: AgentState, db: AsyncSession) -> dict:
    caso_id = state.get("caso_id")
    caso = await db.get(Caso, uuid.UUID(caso_id)) if caso_id else None
    if caso is None:
        # El router solo llega acá con un caso en manos humanas; si no está,
        # se contesta igual antes que dejar al ciudadano sin respuesta.
        logger.warning("espera: no se encontró el caso en manos humanas")
        return {"respuesta": mensaje_espera(), "requiere_escalado": False}

    silencio = await _ya_le_avisaron_por_este_canal(db, caso.id, state.get("canal"))

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="mensaje_en_espera",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={
            "estado": caso.estado.value,
            "asignado": caso.operador_asignado_id is not None,
            "intencion": state.get("intencion"),
            "acuso_recibo": not silencio,
        },
    )
    await db.commit()

    logger.debug(
        "espera: el caso ya lo tiene una persona (acuse=%s)", not silencio
    )
    return {
        # Sin respuesta el mensaje igual se persiste en el caso: el operador lo
        # ve y el caso sigue figurando como esperando respuesta.
        "respuesta": None if silencio else mensaje_espera(caso.referencia),
        # No hay derivación nueva que registrar: el caso ya estaba derivado.
        "requiere_escalado": False,
    }
