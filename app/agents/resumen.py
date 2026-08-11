import logging

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.ejecutor import _texto
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.models import Caso

logger = logging.getLogger(__name__)

SYSTEM_RESUMEN_CASO = """Resumí en 2 o 3 oraciones este caso de atención ciudadana, para \
que un operador entienda de qué se trata sin leer toda la conversación. Incluí qué \
solicita el ciudadano, en qué instancia está la gestión y los datos relevantes \
(dirección, número de trámite, fechas). No incluyas datos de contacto (teléfono/email). \
Respondé solo con el resumen."""

# Las últimas interacciones alcanzan para describir el caso y acotan el costo
# por llamada; el contenido se trunca por si un canal trae mensajes largos.
MAX_INTERACCIONES = 20
MAX_CARACTERES_MENSAJE = 500


async def generar_resumen_caso(db: AsyncSession, caso: Caso) -> str | None:
    """Resumen de la conversación del caso, o None si no hay nada que resumir.

    Las notas internas quedan afuera: no forman parte del contexto del LLM.
    """
    interacciones = await listar_interacciones_de_caso(
        db, caso.id, limite=MAX_INTERACCIONES, incluir_internas=False
    )
    if not interacciones:
        return None

    conversacion = "\n".join(
        f"[{interaccion.actor.value}] {interaccion.contenido[:MAX_CARACTERES_MENSAJE]}"
        for interaccion in interacciones
    )
    respuesta = await llm.get_llm_intake().ainvoke(
        [
            SystemMessage(content=SYSTEM_RESUMEN_CASO),
            HumanMessage(
                content=f"Tipo de caso: {caso.tipo.value}\n"
                f"Estado: {caso.estado.value}\n"
                f"Canal actual: {caso.canal_actual.value}\n\n"
                f"Conversación:\n{conversacion}"
            ),
        ]
    )
    return _texto(respuesta)
