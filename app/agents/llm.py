"""Modelos de lenguaje del grafo, servidos localmente con Ollama.

Las interacciones ciudadanas no salen del organismo: no hay API comercial de por
medio. Ollama corre aparte (mismo patrón que el servicio de ASR/TTS de
`voz_asr_tts/`) y sirve el Qwen2.5-3B ajustado con QLoRA, exportado a GGUF por
el notebook de `finetuning/` y dado de alta con `ollama/Modelfile`.

Los dos roles apuntan al mismo modelo por defecto; se separan en la
configuración para poder medir otro modelo local en uno solo de ellos.

**Herramientas.** El protocolo de tool calling se resuelve acá y no en Ollama.
Ollama arma el prompt de herramientas bien, pero su parser de la respuesta
depende de la versión y de la plantilla: con este modelo devolvía la respuesta
vacía aunque el modelo hubiera generado una llamada correcta. Acá las
herramientas se escriben en el prompt del sistema con el formato exacto de
Qwen2.5 y los bloques `<tool_call>` se leen del texto, así que el
comportamiento no cambia al actualizar Ollama. De paso se acepta el JSON con el
que se ajustó el modelo (`llamada_herramienta`), por si responde en ese formato.
"""

import json
import re
import uuid
from typing import Any, Sequence

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama

from app.core.config import settings

# Texto fijo de la plantilla de chat de Qwen2.5 para declarar herramientas. Es
# lo que el modelo vio en su preentrenamiento: cambiarlo empeora las llamadas.
_ENCABEZADO_TOOLS = (
    "\n\n# Tools\n\nYou may call one or more functions to assist with the user query."
    "\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>"
)
_CIERRE_TOOLS = (
    "\n</tools>\n\nFor each function call, return a json object with function name and "
    "arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'
)
_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|$)", re.DOTALL)


def _sin_sangria(tool: dict) -> dict:
    """La descripción sale del docstring, con la sangría del código adentro:
    tokens que el modelo procesa en cada llamada sin aportar nada."""
    funcion = dict(tool["function"])
    funcion["description"] = " ".join(funcion.get("description", "").split())
    return {**tool, "function": funcion}


def _prompt_de_tools(tools: list[dict]) -> str:
    lineas = "".join("\n" + json.dumps(_sin_sangria(t), ensure_ascii=False) for t in tools)
    return _ENCABEZADO_TOOLS + lineas + _CIERRE_TOOLS


def _llamada(nombre: str, argumentos: Any) -> dict:
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos)
        except json.JSONDecodeError:
            argumentos = {}
    return {
        "name": nombre,
        "args": argumentos if isinstance(argumentos, dict) else {},
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "tool_call",
    }


def a_formato_qwen(mensajes: Sequence[BaseMessage], tools: list[dict]) -> list[BaseMessage]:
    """Reescribe la conversación como la vería Qwen2.5 con su plantilla.

    Las herramientas van al final del prompt del sistema; las llamadas que ya
    hizo el modelo vuelven como bloques `<tool_call>` en su turno, y los
    resultados como `<tool_response>` en un turno del usuario, que es como la
    plantilla de Qwen representa el rol `tool`.
    """
    convertidos: list[BaseMessage] = []
    for mensaje in mensajes:
        if isinstance(mensaje, ToolMessage):
            contenido = mensaje.content if isinstance(mensaje.content, str) else json.dumps(
                mensaje.content, ensure_ascii=False
            )
            convertidos.append(
                HumanMessage(content=f"<tool_response>\n{contenido}\n</tool_response>")
            )
        elif isinstance(mensaje, AIMessage) and mensaje.tool_calls:
            bloques = "\n".join(
                "<tool_call>\n"
                + json.dumps({"name": c["name"], "arguments": c["args"]}, ensure_ascii=False)
                + "\n</tool_call>"
                for c in mensaje.tool_calls
            )
            texto = mensaje.content if isinstance(mensaje.content, str) else ""
            convertidos.append(AIMessage(content=(texto + "\n" if texto else "") + bloques))
        else:
            convertidos.append(mensaje)

    if tools:
        bloque = _prompt_de_tools(tools)
        if convertidos and isinstance(convertidos[0], SystemMessage):
            convertidos[0] = SystemMessage(content=str(convertidos[0].content) + bloque)
        else:
            convertidos.insert(0, SystemMessage(content=bloque.lstrip()))
    return convertidos


def leer_respuesta(texto: str, tools: list[dict]) -> AIMessage:
    """Arma el AIMessage a partir del texto que generó el modelo.

    Reconoce, en este orden: bloques `<tool_call>` (formato de Qwen), el JSON
    del fine-tuning (`llamada_herramienta` + `respuesta`) y, como último caso,
    un JSON suelto con exactamente los parámetros de una sola herramienta (el
    modelo a veces escribe los argumentos sin el envoltorio).
    """
    nombres = {t["function"]["name"] for t in tools}

    llamadas = []
    for bloque in _TOOL_CALL.findall(texto):
        try:
            datos = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        if datos.get("name") in nombres:
            llamadas.append(_llamada(datos["name"], datos.get("arguments", {})))
    if llamadas:
        # Lo que escribe después de la llamada es un resultado inventado ("ya
        # le reservé el turno") antes de que la herramienta corra: se descarta.
        previo = texto.split("<tool_call>", 1)[0].strip()
        return AIMessage(content=previo, tool_calls=llamadas)

    try:
        datos = json.loads(texto.strip())
    except json.JSONDecodeError:
        return AIMessage(content=texto.strip())
    if not isinstance(datos, dict):
        return AIMessage(content=texto.strip())

    if "llamada_herramienta" in datos or "respuesta" in datos:
        pedida = datos.get("llamada_herramienta") or {}
        if pedida.get("nombre") in nombres:
            return AIMessage(
                content="", tool_calls=[_llamada(pedida["nombre"], pedida.get("parametros", {}))]
            )
        return AIMessage(content=str(datos.get("respuesta") or ""))

    candidatas = []
    for tool in tools:
        parametros = tool["function"].get("parameters", {})
        propiedades = set(parametros.get("properties", {}))
        requeridos = set(parametros.get("required", []))
        if set(datos) <= propiedades and requeridos <= set(datos):
            candidatas.append(tool["function"]["name"])
    if len(candidatas) == 1:
        return AIMessage(content="", tool_calls=[_llamada(candidatas[0], datos)])
    return AIMessage(content=texto.strip())


class ChatQwenLocal(ChatOllama):
    """ChatOllama con el protocolo de herramientas de Qwen2.5 resuelto en código."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.bind(tools_qwen=[convert_to_openai_tool(t) for t in tools], **kwargs)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = kwargs.pop("tools_qwen", None)
        if not tools:
            return await super()._agenerate(messages, stop, run_manager, **kwargs)
        resultado = await super()._agenerate(
            a_formato_qwen(messages, tools), stop, run_manager, **kwargs
        )
        return self._con_herramientas(resultado, tools)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = kwargs.pop("tools_qwen", None)
        if not tools:
            return super()._generate(messages, stop, run_manager, **kwargs)
        resultado = super()._generate(a_formato_qwen(messages, tools), stop, run_manager, **kwargs)
        return self._con_herramientas(resultado, tools)

    @staticmethod
    def _con_herramientas(resultado: ChatResult, tools: list[dict]) -> ChatResult:
        generacion = resultado.generations[0]
        texto = generacion.message.content
        mensaje = leer_respuesta(texto if isinstance(texto, str) else str(texto), tools)
        mensaje.response_metadata = generacion.message.response_metadata
        mensaje.usage_metadata = getattr(generacion.message, "usage_metadata", None)
        return ChatResult(generations=[ChatGeneration(message=mensaje)], llm_output=resultado.llm_output)


def _modelo(nombre: str, *, max_tokens: int) -> ChatQwenLocal:
    return ChatQwenLocal(
        model=nombre,
        base_url=settings.ollama_url,
        # Determinístico: clasificar y elegir herramienta no gana nada con
        # variación, y así una misma conversación se puede reproducir.
        temperature=0.0,
        num_ctx=settings.ollama_num_ctx,
        num_predict=max_tokens,
        keep_alive=settings.ollama_keep_alive,
    )


def get_llm_intake() -> ChatQwenLocal:
    return _modelo(settings.agente_modelo_intake, max_tokens=1024)


def get_llm_ejecutor() -> ChatQwenLocal:
    return _modelo(settings.agente_modelo_ejecutor, max_tokens=2048)
