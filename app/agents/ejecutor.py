import json
import logging
import re
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.state import AgentState
from app.db.models import ActorInteraccion, Canal
from app.agents.eleccion import ETIQUETA_TIPO
from app.db.crud import ciudadanos
from app.tools import consultas, reclamos, reservas
from app.tools.reclamos import CategoriaReclamo

logger = logging.getLogger(__name__)

MAX_ITERACIONES = 3
MAX_FALLOS = 1

SYSTEM_EJECUTOR = """Sos el agente de atención ciudadana de un organismo público \
argentino. Resolvés la solicitud del ciudadano de dos maneras: respondés las consultas con la
información del organismo, y ejecutás las gestiones con las herramientas disponibles.

Reglas:
- Tratá al ciudadano de "usted", con lenguaje simple y claro, sin tecnicismos.
- Si la sección "Información del organismo" responde lo que pregunta el ciudadano,
  contestale con esa información y no llames a ninguna herramienta: informar
  requisitos, plazos y horarios es resolver la consulta.
- Usá las herramientas para ejecutar acciones; no inventes números de caso ni estados.
- Al informarle un número de caso al ciudadano usá siempre el campo `referencia`\n  que devuelve la herramienta (ej. REC-5072BFA2). Nunca le muestres `caso_id`.
- Saludá al inicio de la conversación y, si sabés el nombre del ciudadano, usalo.
- Al terminar, confirmá qué se hizo y cuál es el próximo paso.
- Derivá solo si no podés resolver ni con la información del organismo ni con las\n  herramientas. Nunca derives una consulta que ya podés contestar. Cuando\n  corresponda derivar, no te limites a decir que no podés: llamá a\n  `derivar_a_operador` para que una persona la retome."""

FORMATO_TEXTO = """

Formato de la respuesta (el mensaje se lee en WhatsApp o en un correo):
- Escribí en texto plano. Nada de Markdown: ni asteriscos, ni almohadillas, ni guiones
  de lista. El ciudadano ve esos símbolos tal cual, no se convierten en negrita.
- Separá las ideas en párrafos cortos con una línea en blanco entre medio, en vez de
  un bloque largo.
- Cuando informes datos concretos (número de caso, área, plazo, día y hora de un
  turno), poné cada uno en su propia línea con una etiqueta adelante.
- No más de cuatro o cinco líneas de texto corrido por bloque."""

# Un párrafo con "etiqueta: valor" por línea se lee perfecto y se escucha
# rarísimo (el TTS lo sintetiza como una lista entrecortada, con pausas donde
# no las hay en una conversación real). Y cada palabra de más en una llamada
# es audio real que hay que sintetizar y esperar -- ver voz_asr_tts/DEVLOG.md,
# "Diferenciar voz de texto".
FORMATO_VOZ = """

Formato de la respuesta (es una llamada telefónica: se escucha, no se lee):
- Hablá en oraciones completas y fluidas, como en una conversación real. Nunca uses
  listas, numeración ni "etiqueta: valor" en líneas separadas.
- Sé breve: dos o tres oraciones cortas por turno, nunca un discurso largo.
- Si tenés que decir un número de caso, decilo una sola vez y seguí; no lo repitas
  ni lo deletrees letra por letra.
- No ofrezcas un menú de opciones: preguntá una sola cosa concreta por vez."""

# Se agrega al system prompt cuando el ciudadano escribe por primera vez y todavía
# no sabemos quién es. El organismo necesita identificarlo para gestionar cualquier
# trámite a su nombre, así que ese es el primer paso de la conversación.
INSTRUCCION_IDENTIFICACION = """

IMPORTANTE — es el primer contacto y todavía no sabés quién es:
- Arrancá saludando y presentándote como la atención ciudadana del organismo, en una
  línea. Que se note que del otro lado hay un servicio, no un formulario.
- Decile que tomaste nota de lo que necesita, en tus palabras, para que vea que lo
  entendiste antes de pedirle nada.
- Recién ahí pedile su nombre completo y su DNI, explicando en pocas palabras que
  el organismo los necesita para gestionar la solicitud a su nombre.
- Si en este mensaje ya los informó, registralos con `registrar_identidad` y seguí
  con la gestión en la misma respuesta, sin volver a pedirlos.
- Hasta tener esos datos no uses ninguna otra herramienta."""


def construir_tools(db: AsyncSession, state: AgentState) -> list[BaseTool]:
    """Cierra db/ciudadano/canal para que el LLM solo vea los parámetros de negocio."""
    ciudadano_id = uuid.UUID(state["ciudadano_id"])
    canal = Canal(state["canal"])
    # El caso que ya trae la conversación, si `_abrir_caso` lo abrió en un
    # mensaje anterior por faltar un dato para poder ejecutar. Las tools que
    # crean casos lo usan para completar ese caso en vez de abrir otro cuando
    # por fin llega el dato que faltaba.
    caso_id = uuid.UUID(state["caso_id"]) if state.get("caso_id") else None

    @tool
    async def registrar_identidad(nombre_completo: str, documento: str) -> dict:
        """Registra el nombre y el DNI que informó el ciudadano. Usar en cuanto los
        proporcione, antes de gestionar su solicitud. `documento` es solo el número,
        sin puntos ni espacios."""
        ciudadano = await ciudadanos.identificar_ciudadano(
            db, ciudadano_id, documento=documento.strip(), nombre=nombre_completo.strip()
        )
        return {"identificado": True, "nombre": ciudadano.nombre, "documento": ciudadano.documento}

    @tool
    async def derivar_a_operador(motivo: str) -> dict:
        """Deriva la solicitud a un operador humano. Usar cuando el ciudadano pide
        algo que ninguna otra herramienta puede resolver, en vez de limitarse a
        decirle que no se puede. `motivo` describe en una frase qué necesita."""
        return {"derivado": True, "motivo": motivo}

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
            caso_id=caso_id,
        )

    @tool
    async def crear_reserva(turno: str, fecha_hora: str) -> dict:
        """Reserva un turno para el ciudadano en una de las agendas del organismo.
        Usar cuando el ciudadano pide un turno o cita (ej. renovación de licencia,
        atención presencial). `turno` es el nombre de la agenda (la lista de turnos
        disponibles viene en la información del organismo) y `fecha_hora` va en
        formato AAAA-MM-DD HH:MM. Si el ciudadano no dijo día y horario, preguntáselo
        antes de reservar."""
        return await reservas.crear_reserva(
            db,
            ciudadano_id=ciudadano_id,
            canal=canal,
            turno=turno,
            fecha_hora=fecha_hora,
            caso_id=caso_id,
        )

    @tool
    async def consultar_estado_caso(referencia: str = "") -> dict:
        """Consulta el estado de un caso del ciudadano. Usar cuando pregunta cómo
        va un reclamo, reserva o trámite.

        Si el ciudadano identificó de cuál se trata —el número de caso o unas
        palabras de qué era (ej. "el árbol caído", "la renovación del DNI")—,
        pasalo en `referencia`. Si tiene más de un caso y no queda claro a cuál
        se refiere, la herramienta devuelve `varios_posibles=true` con la lista:
        no elijas uno vos, preguntale al ciudadano cuál es antes de responder."""
        return await consultas.consultar_estado_caso(
            db, ciudadano_id=ciudadano_id, referencia=referencia or None
        )

    tools_por_intencion = {
        "reclamo": [crear_reclamo, consultar_estado_caso],
        "reserva": [crear_reserva, consultar_estado_caso],
        "consulta": [consultar_estado_caso],
    }
    tools = tools_por_intencion.get(state["intencion"] or "", [consultar_estado_caso])
    # Sin identificar, el ejecutor tiene que poder registrar el nombre y el DNI
    # en cuanto el ciudadano los informe, cualquiera sea la intención detectada.
    if not state.get("identificado"):
        tools = [registrar_identidad, *tools]
    # Siempre disponible: el ciudadano tiene que poder llegar a una persona,
    # que fue lo más pedido después de la reserva de turnos en la encuesta.
    return [*tools, derivar_a_operador]


def _sin_markdown(texto: str) -> str:
    """Quita el Markdown que el modelo escribe por costumbre.

    WhatsApp usa un solo asterisco para la negrita y el correo va en texto plano:
    en los dos casos un `**` llega literal a la pantalla del ciudadano. El prompt
    ya lo pide, pero el modelo se desvía y esto es la red de seguridad.
    """
    limpio = re.sub(r"\*\*(.+?)\*\*", r"\1", texto, flags=re.S)
    limpio = re.sub(r"__(.+?)__", r"\1", limpio, flags=re.S)
    limpio = re.sub(r"^#{1,6}\s+", "", limpio, flags=re.M)
    return limpio


def _texto(mensaje: AIMessage) -> str:
    if isinstance(mensaje.content, str):
        return _sin_markdown(mensaje.content)
    partes = [
        bloque.get("text", "")
        for bloque in mensaje.content
        if isinstance(bloque, dict) and bloque.get("type") == "text"
    ]
    return _sin_markdown("".join(partes))


async def nodo_ejecutor(state: AgentState, db: AsyncSession) -> dict:
    tools = construir_tools(db, state)
    tools_por_nombre = {t.name: t for t in tools}
    modelo = llm.get_llm_ejecutor().bind_tools(tools)

    contexto_extra = ""
    if state.get("conocimiento"):
        contexto_extra = (
            "\n\nInformación del organismo (fuente oficial: usala para responder "
            "consultas sobre requisitos, plazos y horarios):\n"
            + "\n".join(state["conocimiento"])
        )
    if state.get("origen_menu"):
        # El mensaje que sigue es el número que tocó en el menú de inicio, no
        # una descripción: sin este aviso, el modelo ve un "1" o un "2" sueltos
        # y o los ignora (vuelve a saludar) o le pregunta al ciudadano qué quiso
        # decir con el número.
        etiqueta = ETIQUETA_TIPO.get(state["origen_menu"], state["origen_menu"])
        contexto_extra += (
            f'\n\nEl ciudadano acaba de elegir "{etiqueta}" en el menú de inicio '
            "(el mensaje que sigue es solo el número de esa opción, no una "
            "descripción). Todavía no contó de qué se trata: arrancá preguntándole "
            "eso, en una frase, sin repetirle el saludo ni el menú."
        )

    # El historial del caso entra como turnos previos de la conversación. Sin
    # esto el ejecutor solo ve el mensaje actual y le vuelve a preguntar al
    # ciudadano algo que ya dijo antes, que es justamente lo que el proyecto
    # busca evitar. El nodo de contexto ya lo trae sin las notas internas.
    formato = FORMATO_VOZ if Canal(state["canal"]) == Canal.voz else FORMATO_TEXTO
    mensajes: list = [SystemMessage(content=SYSTEM_EJECUTOR + formato + contexto_extra)]
    for entrada in state.get("historial") or []:
        contenido = entrada.get("contenido") or ""
        if not contenido:
            continue
        if entrada.get("actor") == ActorInteraccion.ciudadano.value:
            mensajes.append(HumanMessage(content=contenido))
        else:
            # Agente u operador: para el ciudadano, los dos son el organismo.
            mensajes.append(AIMessage(content=contenido))
    mensajes.append(HumanMessage(content=state["mensaje"]))

    resultado_ejecucion: dict = {}
    caso_id = state.get("caso_id")
    fallos = 0

    for _ in range(MAX_ITERACIONES):
        respuesta_llm: AIMessage = await modelo.ainvoke(mensajes)

        if not respuesta_llm.tool_calls:
            derivacion = resultado_ejecucion.get("derivar_a_operador")
            if derivacion:
                return {
                    "resultado_ejecucion": resultado_ejecucion,
                    "caso_id": caso_id,
                    "requiere_escalado": True,
                    "motivo_escalado": "sin_herramienta",
                }
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
