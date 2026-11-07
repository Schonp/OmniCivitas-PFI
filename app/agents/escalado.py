import logging
from datetime import datetime, timezone
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.core.config import settings
from app.agents.ejecutor import _texto
from app.agents.eleccion import ETIQUETA_TIPO
from app.agents.state import AgentState
from app.agents.titulos import titulo_automatico
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.crud.casos import asignar_caso
from app.db.crud.usuarios import elegir_operador_con_menos_casos_activos
from app.db.models import ActorInteraccion, Canal, Caso, EstadoCaso, TipoCaso
from app.tools import ACTOR_AGENTE

logger = logging.getLogger(__name__)

# El aviso de derivación es lo último que lee el ciudadano antes de quedarse
# esperando. Si no dice por qué interviene una persona ni con qué número
# reclamar después, se lee como un rechazo. El motivo interno se traduce a algo
# que la persona entienda, sin exponer el vocabulario del sistema.
MOTIVO_EN_CRIOLLO = {
    "solicita_humano": (
        "Por supuesto. Lo pongo en contacto con una persona del equipo."
    ),
    "confianza_baja": (
        "Prefiero que una persona del equipo revise lo que me plantea, "
        "así evitamos darle una respuesta equivocada."
    ),
    "sin_herramienta": (
        "Su pedido necesita una gestión que no puedo resolver yo, "
        "así que lo va a tomar una persona del equipo."
    ),
    "ciudadano_no_identificado": (
        "Para avanzar con esto hace falta verificar sus datos, "
        "y eso lo hace una persona del equipo."
    ),
    # RNF-02: el modelo no está disponible. El ciudadano no tiene por qué
    # enterarse del detalle técnico, pero sí de que alguien lo va a atender.
    "falla_tecnica": (
        "En este momento no puedo procesar su mensaje, "
        "así que lo va a atender una persona del equipo."
    ),
}

APERTURA_POR_DEFECTO = (
    "Voy a derivar su pedido a una persona del equipo para que lo resuelva."
)

CIERRE_ESCALADO = (
    "Lo van a contactar por este mismo medio dentro del horario de atención. "
    "No hace falta que vuelva a escribir."
)

# Todavía no hay operadores atendiendo por teléfono: el seguimiento de una
# llamada derivada no puede volver "por este mismo medio" como en WhatsApp o
# email, porque no hay nadie para tomarlo ahí. Se avisa explícitamente que el
# contacto va a ser por WhatsApp en vez de dejarlo implícito (ver DEVLOG.md de
# voz_asr_tts, "Diferenciar voz de texto").
CIERRE_ESCALADO_VOZ = (
    "Lo van a contactar por WhatsApp dentro del horario de atención, "
    "ya que por teléfono todavía no hay un equipo disponible para seguir esto."
)

# Se conserva el texto plano: el intake descarta el aviso de escalado del
# historial para no releerlo como si fuera un pedido del ciudadano.
RESPUESTA_ESCALADO = APERTURA_POR_DEFECTO + " " + CIERRE_ESCALADO


def mensaje_escalado(
    motivo: str | None, referencia: str | None = None, canal: Canal | None = None
) -> str:
    """Arma el aviso explicando el porqué y dejando la referencia del caso.

    Sin la referencia el ciudadano no tiene con qué reclamar después.
    """
    partes = [MOTIVO_EN_CRIOLLO.get(motivo or "", APERTURA_POR_DEFECTO)]
    if referencia and canal != Canal.voz:
        # Por llamada no se dicta: no hay dónde anotarlo, y el caso se
        # encuentra por el número de teléfono.
        partes.append(f"Su pedido quedó registrado con el número {referencia}.")
    partes.append(CIERRE_ESCALADO_VOZ if canal == Canal.voz else CIERRE_ESCALADO)
    return "\n\n".join(partes)

SYSTEM_RESUMEN = """Resumí en 2 o 3 oraciones la solicitud del ciudadano para que un \
operador humano la retome. Incluí la intención detectada y los datos relevantes. \
No incluyas datos de contacto (teléfono/email)."""

TIPOS_VALIDOS = {t.value for t in TipoCaso}


async def _generar_resumen(state: AgentState) -> str:
    if state.get("origen_menu"):
        # El mensaje real es el número que tocó en el menú ("3"), no una
        # descripción: pedirle un resumen al LLM sobre eso no tiene nada para
        # resumir y termina inventando (llegó a contestarle al ciudadano en
        # vez de resumirle al operador). Acá se sabe exactamente qué pasó, así
        # que no hace falta el LLM.
        etiqueta = ETIQUETA_TIPO.get(state["origen_menu"], state["origen_menu"])
        return f'Eligió "{etiqueta}" en el menú de inicio, sin dar más detalle todavía.'
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


def _motivo_real(state: AgentState) -> str:
    """El motivo por defecto era siempre "confianza_baja", aunque el caso
    escalara por otra razón: la auditoría llegaba a decir confianza baja al lado
    de una confianza de 0.85. Se deriva del mismo criterio que usa el router."""
    if state["confianza"] < settings.agente_umbral_confianza:
        return "confianza_baja"
    if state["intencion"] in ("otro", "tramite"):
        return "sin_herramienta"
    if state.get("ciudadano_id") is None:
        return "ciudadano_no_identificado"
    return "confianza_baja"


async def _asignar_operador(db: AsyncSession, caso: Caso) -> Caso:
    operador = await elegir_operador_con_menos_casos_activos(db)
    if operador is None:
        logger.warning("escalado: no hay operadores activos, el caso queda sin asignar")
        return caso
    return await asignar_caso(
        db, caso, operador, actor=ACTOR_AGENTE, actor_tipo=ActorInteraccion.agente_ia
    )


async def escalar_caso_por_falla(db: AsyncSession, caso_id: uuid.UUID, motivo: str) -> None:
    """Deriva un caso que ya existe cuando falla algo fuera del grafo (RNF-02).

    Lo usa el envío saliente: si Meta o el servidor de correo rechazan la
    respuesta del agente, el ciudadano no la recibe, y tiene que retomarlo una
    persona. Un caso que ya está en manos de un operador o cerrado no se toca.
    """
    caso = await db.get(Caso, caso_id)
    if caso is None or caso.estado in (EstadoCaso.escalado, EstadoCaso.cerrado) or caso.en_manos_humanas:
        return
    caso.estado = EstadoCaso.escalado
    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="escalado",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"motivo": motivo},
    )
    await db.commit()
    await _asignar_operador(db, caso)


async def nodo_escalado(state: AgentState, db: AsyncSession) -> dict:
    motivo = state.get("motivo_escalado") or _motivo_real(state)
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
            "respuesta": mensaje_escalado(motivo, canal=Canal(state["canal"])),
        }

    # El operador tiene que ver de qué se trata sin leer todo el hilo ni pedir
    # el resumen a mano: al derivar, se deja escrito en el caso.
    caso.resumen_ia = resumen
    caso.resumen_ia_generado_en = datetime.now(timezone.utc)
    # Un caso derivado antes de que ninguna tool lo nombrara se titula con lo
    # primero que pidió el vecino (o con este mensaje, si es el primero).
    if not caso.titulo:
        primeros = await primeros_mensajes_de_casos(db, [caso.id])
        caso.titulo = titulo_automatico(caso.tipo, primeros.get(caso.id) or state.get("mensaje"))

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="escalado",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"motivo": motivo, "resumen": resumen},
    )
    await db.commit()

    # Reparte la carga en vez de dejarlo en la bandeja general esperando a que
    # un supervisor lo distribuya a mano. Nunca un supervisor: ve y reparte el
    # organismo entero, no atiende su propia bandeja. Reusa `asignar_caso` para
    # que la asignación automática deje exactamente el mismo rastro (estado
    # `en_progreso`, auditoría `asignacion`) que si un supervisor la hubiera
    # hecho a mano — solo cambia quién la hizo.
    caso = await _asignar_operador(db, caso)

    return {
        "caso_id": str(caso.id),
        "requiere_escalado": True,
        "motivo_escalado": motivo,
        "respuesta": mensaje_escalado(motivo, caso.referencia, canal=Canal(state["canal"])),
    }
