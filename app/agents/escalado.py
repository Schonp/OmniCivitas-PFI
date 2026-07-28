import logging
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.ejecutor import _texto
from app.agents.state import AgentState
from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, Canal, Caso, EstadoCaso, TipoCaso
from app.tools import ACTOR_AGENTE

logger = logging.getLogger(__name__)

RESPUESTA_ESCALADO = (
    "Su solicitud fue derivada a un operador, que lo contactará a la brevedad "
    "por este mismo medio. Gracias por comunicarse."
)

SYSTEM_RESUMEN = """Resumí en 2 o 3 oraciones la solicitud del ciudadano para que un \
operador humano la retome. Incluí la intención detectada y los datos relevantes. \
No incluyas datos de contacto (teléfono/email)."""

TIPOS_VALIDOS = {t.value for t in TipoCaso}


async def _generar_resumen(state: AgentState) -> str:
    try:
        respuesta = await llm.get_llm_intake().ainvoke(
            [
                SystemMessage(content=SYSTEM_RESUMEN),
                HumanMessage(
                    content=f"Intención detectada: {state.get('intencion')}\n"
                    f"Mensaje: {state['mensaje']}"
                ),
            ]
        )
        return _texto(respuesta)
    except Exception:
        logger.exception("escalado: fallo el resumen LLM, uso el mensaje original")
        return state["mensaje"][:500]


async def nodo_escalado(state: AgentState, db: AsyncSession) -> dict:
    motivo = state.get("motivo_escalado") or "confianza_baja"
    resumen = await _generar_resumen(state)

    caso_id = state.get("caso_id")
    if caso_id is not None:
        caso = await db.get(Caso, uuid.UUID(caso_id))
        caso.estado = EstadoCaso.escalado
    elif state.get("ciudadano_id") is not None:
        tipo = state.get("intencion")
        caso = Caso(
            ciudadano_id=uuid.UUID(state["ciudadano_id"]),
            tipo=TipoCaso(tipo) if tipo in TIPOS_VALIDOS else TipoCaso.consulta,
            estado=EstadoCaso.escalado,
            canal_origen=Canal(state["canal"]),
            canal_actual=Canal(state["canal"]),
        )
        db.add(caso)
        await db.flush()
    else:
        # Ciudadano no identificado: no hay caso que persistir ni auditar.
        logger.debug("escalado: ciudadano no identificado, sin caso (motivo=%s)", motivo)
        return {
            "requiere_escalado": True,
            "motivo_escalado": motivo,
            "respuesta": RESPUESTA_ESCALADO,
        }

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="escalado",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"motivo": motivo, "resumen": resumen},
    )
    await db.commit()

    return {
        "caso_id": str(caso.id),
        "requiere_escalado": True,
        "motivo_escalado": motivo,
        "respuesta": RESPUESTA_ESCALADO,
    }
