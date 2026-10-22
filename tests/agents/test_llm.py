from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents import llm


@tool
def crear_reserva(turno: str, fecha_hora: str) -> dict:
    """Reserva un turno."""
    return {}


@tool
def consultar_estado_caso(referencia: str = "") -> dict:
    """Consulta el estado de un caso."""
    return {}


TOOLS = [convert_to_openai_tool(crear_reserva), convert_to_openai_tool(consultar_estado_caso)]


def test_lee_el_bloque_tool_call_y_descarta_lo_que_inventa_despues():
    """El modelo sigue escribiendo después de la llamada ("ya le reservé") antes
    de que la herramienta corra: ese texto no puede llegar al ciudadano."""
    texto = (
        '<tool_call>\n{"name": "crear_reserva", "arguments": {"turno": "DNI", '
        '"fecha_hora": "2026-12-01 12:00"}}\n</tool_call>\nLe reservé el turno de DNI.'
    )

    mensaje = llm.leer_respuesta(texto, TOOLS)

    assert mensaje.content == ""
    assert [(c["name"], c["args"]) for c in mensaje.tool_calls] == [
        ("crear_reserva", {"turno": "DNI", "fecha_hora": "2026-12-01 12:00"})
    ]
    assert mensaje.tool_calls[0]["id"]


def test_acepta_una_llamada_sin_la_etiqueta_de_cierre():
    texto = '<tool_call>\n{"name": "consultar_estado_caso", "arguments": {"referencia": "semáforo"}}'

    mensaje = llm.leer_respuesta(texto, TOOLS)

    assert mensaje.tool_calls[0]["args"] == {"referencia": "semáforo"}


def test_ignora_una_herramienta_que_no_se_ofrecio():
    texto = '<tool_call>\n{"name": "borrar_todo", "arguments": {}}\n</tool_call>'

    assert llm.leer_respuesta(texto, TOOLS).tool_calls == []


def test_entiende_el_formato_del_fine_tuning():
    texto = (
        '{"intencion": "consulta", "confianza": 0.9, "llamada_herramienta": '
        '{"nombre": "consultar_estado_caso", "parametros": {"referencia": "la poda"}}, '
        '"respuesta": "Un momento."}'
    )

    mensaje = llm.leer_respuesta(texto, TOOLS)

    assert mensaje.tool_calls[0]["name"] == "consultar_estado_caso"
    assert mensaje.tool_calls[0]["args"] == {"referencia": "la poda"}


def test_del_formato_del_fine_tuning_sin_llamada_queda_la_respuesta():
    texto = '{"intencion": "reclamo", "llamada_herramienta": null, "respuesta": "¿En qué calle?"}'

    mensaje = llm.leer_respuesta(texto, TOOLS)

    assert mensaje.tool_calls == []
    assert mensaje.content == "¿En qué calle?"


def test_un_json_con_los_parametros_de_una_sola_herramienta_es_esa_llamada():
    mensaje = llm.leer_respuesta('{"turno": "CeSAC", "fecha_hora": "2026-11-28 13:00"}', TOOLS)

    assert mensaje.tool_calls[0]["name"] == "crear_reserva"


def test_el_texto_comun_queda_como_respuesta():
    mensaje = llm.leer_respuesta("¿Me indica la dirección exacta?", TOOLS)

    assert mensaje.tool_calls == []
    assert mensaje.content == "¿Me indica la dirección exacta?"


def test_la_conversacion_se_reescribe_con_la_plantilla_de_qwen():
    llamada = {"name": "crear_reserva", "args": {"turno": "DNI"}, "id": "c1", "type": "tool_call"}
    mensajes = [
        SystemMessage(content="Sos el agente."),
        HumanMessage(content="Quiero un turno"),
        AIMessage(content="", tool_calls=[llamada]),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
    ]

    convertidos = llm.a_formato_qwen(mensajes, TOOLS)

    assert convertidos[0].content.startswith("Sos el agente.\n\n# Tools")
    assert '"name": "crear_reserva"' in convertidos[0].content
    assert convertidos[2].content == (
        '<tool_call>\n{"name": "crear_reserva", "arguments": {"turno": "DNI"}}\n</tool_call>'
    )
    assert isinstance(convertidos[3], HumanMessage)
    assert convertidos[3].content == '<tool_response>\n{"ok": true}\n</tool_response>'


def test_los_modelos_apuntan_a_ollama_local():
    modelo = llm.get_llm_ejecutor()

    assert isinstance(modelo, llm.ChatQwenLocal)
    assert modelo.base_url == llm.settings.ollama_url
    assert modelo.temperature == 0.0
