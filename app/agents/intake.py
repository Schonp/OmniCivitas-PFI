import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import llm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contexto import obtener_ciudadano_por_canal
from app.agents.eleccion import ETIQUETA_TIPO, resolver, resolver_voz
from app.agents.escalado import RESPUESTA_ESCALADO
from app.agents.state import AgentState
from app.db.crud.casos import obtener_caso_activo_de_ciudadano
from app.db.crud.interacciones import listar_interacciones_de_caso
from app.db.models import Canal

HISTORIAL_MAX_INTAKE = 20
from app.schemas.agente import ClasificacionIntent

logger = logging.getLogger(__name__)

SYSTEM_INTAKE = """Sos el clasificador de intenciones de una plataforma de atención \
ciudadana de un organismo público argentino. Analizá el mensaje del ciudadano y \
clasificalo en una de estas intenciones: saludo, consulta, reclamo, reserva, tramite, otro.

Qué significa cada intención:
- "saludo": solo un saludo o una cortesía, sin pedido concreto ("hola", "buenas", "gracias", "estás ahí?"). Si además pide algo, gana la intención del pedido. Pedir hablar con una persona ("quiero hablar con un operador") NO es un saludo: es un pedido, clasificalo por el tema que traiga o como "consulta", y marcá requiere_humano=true.
- "reclamo": el ciudadano avisa de un problema, una falla o una situación del espacio público o de un servicio que el organismo debería atender: vereda rota, luminaria quemada, basura sin recolectar, ruidos molestos, un árbol caído, un animal suelto o perdido. "Quiero reportar", "hay un", "no funciona", "hace días que" son reclamos, aunque el ciudadano no use esa palabra y aunque no sea evidente qué área lo resuelve.
- "consulta": pide información —requisitos, horarios, plazos, direcciones, qué gestiones se pueden hacer— o pregunta cómo viene algo que ya inició.
- "reserva": pide un turno o una cita.
- "tramite": quiere iniciar o continuar una gestión formal (licencia, habilitación, certificado).
- "otro": nada de lo anterior. Es el último recurso, no el cajón de lo difícil: antes de elegirlo fijate si lo que trae es un problema para reportar (reclamo) o una pregunta (consulta). Que no sepas qué área lo atiende no lo convierte en "otro".

Además:
- Extraé entidades relevantes (categoría, dirección, fecha, número de trámite, etc.).
- Asigná una confianza entre 0 y 1 según qué tan clara es la intención.
- Marcá requiere_humano=true si el ciudadano pide explícitamente hablar con una \
persona, o si la solicitud involucra datos sensibles (denuncias, documentación legal).
- Un saludo nunca continúa un caso: con intencion="saludo" marcá siempre continua_caso_abierto=false, para que no se pegue al último caso abierto.
- Marcá continua_caso_abierto=false solo si el mensaje trata de un asunto distinto al del historial. Preguntar por el estado de algo que ya se gestionó, aportar un dato pedido o responder una pregunta del agente son continuaciones."""


def _formatear_historial(historial: list[dict]) -> str:
    if not historial:
        return ""
    lineas = [f"[{i['actor']}] {i['contenido']}" for i in historial]
    return "Historial reciente de la conversación:\n" + "\n".join(lineas) + "\n\n"


async def _historial_del_caso(state: AgentState, db: AsyncSession) -> list[dict]:
    """El nodo contexto corre después del intake, así que acá el historial todavía
    no está en el estado. Sin él, un mensaje de continuación ("renovación de
    licencia") se clasifica de cero y puede desviar el flujo que ya venía."""
    ciudadano = await obtener_ciudadano_por_canal(
        db, Canal(state["canal"]), state["identificador"]
    )
    if ciudadano is None:
        return []
    caso = await obtener_caso_activo_de_ciudadano(db, ciudadano.id)
    if caso is None:
        return []
    interacciones = await listar_interacciones_de_caso(
        db, caso.id, limite=HISTORIAL_MAX_INTAKE, incluir_internas=False
    )
    # El aviso fijo de escalado es chrome del organismo, no algo que dijo el
    # ciudadano: si entra al historial, el clasificador lee "derivado a un
    # operador" y marca requiere_humano en todos los mensajes siguientes.
    return [
        {"actor": i.actor.value, "contenido": i.contenido}
        for i in interacciones
        if i.contenido != RESPUESTA_ESCALADO
    ]


# El ciudadano dice explícitamente que es otro tema. Por voz el saludo le
# pregunta "¿quiere seguir con ese o es algo nuevo?", y el clasificador llegó a
# tomar "Quiero reportar algo nuevo" como continuación del reclamo anterior: el
# reclamo nuevo quedó registrado en el caso viejo, mezclado con otro tema.
_PIDE_TEMA_NUEVO = re.compile(
    r"\b(?:algo|otro|otra)\s+(?:nuevo|nueva|distinto|distinta|diferente)\b"
    r"|\botra\s+cosa\b"
    r"|\botro\s+(?:tema|reclamo|pedido|problema|asunto|turno|tr[aá]mite)\b"
    r"|\b(?:un|una)\s+(?:nuevo|nueva)\s+(?:reclamo|consulta|pedido|tr[aá]mite|turno)\b"
    r"|\bnuev[oa]\s+(?:reclamo|consulta|pedido|tr[aá]mite|turno)\b",
    re.IGNORECASE,
)


def pide_tema_nuevo(mensaje: str) -> bool:
    return bool(_PIDE_TEMA_NUEVO.search(mensaje or ""))


# El mensaje entero es "quiero algo nuevo", sin decir qué. No hay nada que
# clasificar: el modelo lo tomaba como "trámite" y lo derivaba a una persona.
_SOLO_ALGO_NUEVO = re.compile(
    r"^(?:(?:hola|buenas|buen día|buen dia|sí|si|no|bueno|eh)[,.]?\s+)*"
    r"(?:(?:es|sería|seria)\s+)?"
    r"(?:(?:quiero|quisiera|necesito|me gustaría|me gustaria|vengo a|voy a)\s+)?"
    r"(?:(?:hacer|iniciar|empezar|arrancar|pedir|plantear|consultar|reportar)\s+)?"
    r"(?:algo\s+(?:nuevo|distinto|diferente)|otra\s+cosa|otro\s+tema|otro\s+pedido"
    r"|otra\s+gesti[oó]n|una\s+nueva\s+gesti[oó]n|una\s+gesti[oó]n\s+nueva|una\s+gesti[oó]n"
    r"|un\s+nuevo\s+pedido|un\s+pedido\s+nuevo|uno\s+nuevo|nuevo|nueva)"
    r"[.!¡¿?\s]*$",
    re.IGNORECASE,
)


def pide_algo_nuevo_sin_decir_que(mensaje: str) -> bool:
    return bool(_SOLO_ALGO_NUEVO.match((mensaje or "").strip()))


def _desde_la_eleccion(oferta: dict) -> dict:
    """El ciudadano eligió del menú: no hay nada que clasificar."""
    if "caso_id" in oferta:
        return {
            "caso_elegido": oferta["caso_id"],
            "intencion": "consulta",
            "entidades": {},
            "confianza": 1.0,
            "continua_caso_abierto": True,
            "requiere_escalado": False,
            "motivo_escalado": None,
            "ofertas": [],
        }
    return {
        "intencion": oferta["intencion"],
        "entidades": {},
        "confianza": 1.0,
        # Eligió un tipo, no continuó un caso: arranca uno nuevo.
        "continua_caso_abierto": False,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "ofertas": [],
        # Para que ejecutor y escalado sepan que el "1"/"2"/"3" no es el
        # mensaje real: es la elección, y todavía no dijo de qué se trata.
        "origen_menu": oferta["intencion"] if oferta["intencion"] in ETIQUETA_TIPO else None,
    }


async def nodo_intake(state: AgentState, db: AsyncSession) -> dict:
    # Un "4" pelado no se le pregunta al modelo: se resuelve contra lo que se
    # ofreció. Las ofertas se consumen para que un número suelto de mañana no
    # caiga en la lista de hoy.
    por_voz = state.get("canal") == "voz"
    ofertas = state.get("ofertas") or []
    oferta = (resolver_voz if por_voz else resolver)(state["mensaje"], ofertas)
    if oferta is not None:
        logger.debug("intake: el ciudadano eligió la opción %s", oferta["numero"])
        return _desde_la_eleccion(oferta)

    if pide_algo_nuevo_sin_decir_que(state["mensaje"]):
        return {
            "pide_algo_nuevo": True,
            "intencion": "otro",
            "entidades": {},
            "confianza": 0.0,
            "continua_caso_abierto": False,
            "requiere_escalado": False,
            "motivo_escalado": None,
            "ofertas": [],
        }

    # Por voz el saludo acaba de ofrecerle sus casos abiertos y no eligió
    # ninguno: lo que cuenta es algo nuevo, no la continuación del último.
    nuevo_tras_ofrecer = por_voz and bool(ofertas)

    historial = state.get("historial") or await _historial_del_caso(state, db)
    clasificador = llm.get_llm_intake().with_structured_output(ClasificacionIntent)
    mensajes = [
        SystemMessage(content=SYSTEM_INTAKE),
        HumanMessage(
            content=_formatear_historial(historial)
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
    salida = {
        "continua_caso_abierto": resultado.continua_caso_abierto
        and not pide_tema_nuevo(state["mensaje"])
        and not nuevo_tras_ofrecer,
        "intencion": resultado.intencion,
        "entidades": resultado.entidades,
        "confianza": resultado.confianza,
        "requiere_escalado": resultado.requiere_humano,
        "motivo_escalado": "solicita_humano" if resultado.requiere_humano else None,
    }
    if por_voz:
        # Las ofertas de la llamada valen para la respuesta al saludo, no para
        # los turnos que siguen.
        salida["ofertas"] = []
    return salida
