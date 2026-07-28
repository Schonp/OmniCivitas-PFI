import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import llm
from app.agents.state import AgentState
from app.schemas.agente import ClasificacionIntent

logger = logging.getLogger(__name__)

SYSTEM_INTAKE = """Sos el clasificador de intenciones de una plataforma de atención \
ciudadana de un organismo público argentino. Analizá el mensaje del ciudadano y \
clasificalo en una de estas intenciones: consulta, reclamo, reserva, tramite, otro.

- Extraé entidades relevantes (categoría, dirección, fecha, número de trámite, etc.).
- Asigná una confianza entre 0 y 1 según qué tan clara es la intención.
- Marcá requiere_humano=true si el ciudadano pide explícitamente hablar con una \
persona, o si la solicitud involucra datos sensibles (denuncias, documentación legal).
- Si la intención no encaja en ninguna categoría, usá "otro" con confianza baja."""


def _formatear_historial(historial: list[dict]) -> str:
    if not historial:
        return ""
    lineas = [f"[{i['actor']}] {i['contenido']}" for i in historial]
    return "Historial reciente de la conversación:\n" + "\n".join(lineas) + "\n\n"


async def nodo_intake(state: AgentState) -> dict:
    clasificador = llm.get_llm_intake().with_structured_output(ClasificacionIntent)
    mensajes = [
        SystemMessage(content=SYSTEM_INTAKE),
        HumanMessage(
            content=_formatear_historial(state.get("historial") or [])
            + f"Mensaje del ciudadano (canal {state['canal']}): {state['mensaje']}"
        ),
    ]
    resultado: ClasificacionIntent = await clasificador.ainvoke(mensajes)

    logger.debug(
        "intake: intencion=%s confianza=%.2f requiere_humano=%s",
        resultado.intencion,
        resultado.confianza,
        resultado.requiere_humano,
    )
    return {
        "intencion": resultado.intencion,
        "entidades": resultado.entidades,
        "confianza": resultado.confianza,
        "requiere_escalado": resultado.requiere_humano,
        "motivo_escalado": "solicita_humano" if resultado.requiere_humano else None,
    }
