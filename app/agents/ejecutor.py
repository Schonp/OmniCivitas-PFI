import json
import logging
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.state import AgentState
from app.db.models import Canal
from app.tools import consultas, reclamos, reservas
from app.tools.reclamos import CategoriaReclamo

logger = logging.getLogger(__name__)

MAX_ITERACIONES = 3
MAX_FALLOS = 1

SYSTEM_EJECUTOR = """Sos el agente de atención ciudadana de un organismo público \
argentino. Resolvés la solicitud del ciudadano usando las herramientas disponibles.

Reglas:
- Tratá al ciudadano de "usted", con lenguaje simple y claro, sin tecnicismos.
- Usá las herramientas para ejecutar acciones; no inventes números de caso ni estados.
- Al terminar, respondé en un párrafo breve confirmando qué se hizo y los próximos pasos.
- Si no podés resolver la solicitud con las herramientas, decilo explícitamente."""


def construir_tools(db: AsyncSession, state: AgentState) -> list[BaseTool]:
    """Cierra db/ciudadano/canal para que el LLM solo vea los parámetros de negocio."""
    ciudadano_id = uuid.UUID(state["ciudadano_id"])
    canal = Canal(state["canal"])

    @tool
    async def crear_reclamo(descripcion: str, categoria: CategoriaReclamo) -> dict:
        """Crea un nuevo reclamo para el ciudadano. Usar cuando el ciudadano expresa
        una queja o problema con un servicio público (ej. vereda rota, luminaria
        quemada, falta de recolección)."""
        return await reclamos.crear_reclamo(
            db,
            ciudadano_id=ciudadano_id,
            canal=canal,
            descripcion=descripcion,
            categoria=categoria,
        )

    @tool
    async def crear_reserva(descripcion: str, fecha_solicitada: str) -> dict:
        """Crea una reserva de turno para el ciudadano. Usar cuando el ciudadano pide
        un turno o cita (ej. renovación de licencia, atención presencial).
        fecha_solicitada en formato AAAA-MM-DD."""
        return await reservas.crear_reserva(
            db,
            ciudadano_id=ciudadano_id,
            canal=canal,
            descripcion=descripcion,
            fecha_solicitada=fecha_solicitada,
        )

    @tool
    async def consultar_estado_caso() -> dict:
        """Consulta el estado del caso más reciente del ciudadano. Usar cuando el
        ciudadano pregunta cómo va su reclamo, reserva o trámite."""
        return await consultas.consultar_estado_caso(db, ciudadano_id=ciudadano_id)

    tools_por_intencion = {
        "reclamo": [crear_reclamo, consultar_estado_caso],
        "reserva": [crear_reserva, consultar_estado_caso],
        "consulta": [consultar_estado_caso],
    }
    return tools_por_intencion.get(state["intencion"] or "", [consultar_estado_caso])


def _texto(mensaje: AIMessage) -> str:
    if isinstance(mensaje.content, str):
        return mensaje.content
    partes = [
        bloque.get("text", "")
        for bloque in mensaje.content
        if isinstance(bloque, dict) and bloque.get("type") == "text"
    ]
    return "".join(partes)


async def nodo_ejecutor(state: AgentState, db: AsyncSession) -> dict:
    tools = construir_tools(db, state)
    tools_por_nombre = {t.name: t for t in tools}
    modelo = llm.get_llm_ejecutor().bind_tools(tools)

    contexto_extra = ""
    if state.get("conocimiento"):
        contexto_extra = "\n\nInformación del organismo:\n" + "\n".join(state["conocimiento"])

    mensajes: list = [
        SystemMessage(content=SYSTEM_EJECUTOR + contexto_extra),
        HumanMessage(content=state["mensaje"]),
    ]

    resultado_ejecucion: dict = {}
    caso_id = state.get("caso_id")
    fallos = 0

    for _ in range(MAX_ITERACIONES):
        respuesta_llm: AIMessage = await modelo.ainvoke(mensajes)

        if not respuesta_llm.tool_calls:
            return {
                "resultado_ejecucion": resultado_ejecucion or None,
                "caso_id": caso_id,
                "respuesta": _texto(respuesta_llm),
            }

        mensajes.append(respuesta_llm)
        for tool_call in respuesta_llm.tool_calls:
            herramienta = tools_por_nombre[tool_call["name"]]
            try:
                salida = await herramienta.ainvoke(tool_call["args"])
            except Exception:
                logger.exception("ejecutor: fallo la tool %s", tool_call["name"])
                fallos += 1
                if fallos > MAX_FALLOS:
                    return {
                        "resultado_ejecucion": resultado_ejecucion or None,
                        "caso_id": caso_id,
                        "requiere_escalado": True,
                        "motivo_escalado": "fallo_ejecucion",
                    }
                salida = {"error": "La acción falló, intente de otra forma."}

            if isinstance(salida, dict):
                resultado_ejecucion[tool_call["name"]] = salida
                caso_id = salida.get("caso_id", caso_id)
            mensajes.append(
                ToolMessage(
                    content=json.dumps(salida, default=str, ensure_ascii=False),
                    tool_call_id=tool_call["id"],
                )
            )

    return {
        "resultado_ejecucion": resultado_ejecucion or None,
        "caso_id": caso_id,
        "requiere_escalado": True,
        "motivo_escalado": "iteraciones_agotadas",
    }
