import logging
import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.aviso_ia import anteponer_aviso
from app.agents.cancelacion import es_gestion_de_turno
from app.agents.contexto import nodo_contexto, obtener_ciudadano_por_canal
from app.agents.ejecutor import nodo_ejecutor
from app.agents.identidad import responde_con_su_identidad
from app.agents.escalado import mensaje_escalado, nodo_escalado
from app.agents.espera import nodo_espera
from app.agents.intake import nodo_intake
from app.agents.opciones import nodo_opciones
from app.agents.saludo import nodo_saludo
from app.agents.seguridad import con_aviso_de_seguridad, ofrece_dato_sensible
from app.agents.state import AgentState
from app.core.config import settings
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.casos import obtener_caso_activo_de_ciudadano
from app.db.crud.interacciones import crear_interaccion
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.tools import ACTOR_AGENTE

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


async def iniciar_checkpointer() -> None:
    """Abre el pool y crea las tablas del checkpointer al arrancar la app.

    No puede hacerse dentro de un request: `setup()` usa CREATE INDEX CONCURRENTLY,
    que espera a que cierren todas las transacciones abiertas — incluida la del
    propio request, que ya consultó el caso del ciudadano. Se bloquearía contra
    sí mismo.
    """
    global _pool, _checkpointer
    if _checkpointer is not None:
        return

    url = settings.database_url.replace("postgresql+asyncpg", "postgresql")
    _pool = AsyncConnectionPool(
        url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _pool.open(wait=True)
    _checkpointer = AsyncPostgresSaver(_pool)
    await _checkpointer.setup()
    logger.info("checkpointer de LangGraph inicializado")


async def borrar_hilos(hilos: list[str]) -> None:
    """Borra del checkpointer las conversaciones de esos hilos.

    El estado del grafo guarda los mensajes del ciudadano tal cual: sin esto,
    una baja (RF-13) dejaría su conversación entera en las tablas del
    checkpointer aunque se hubiera anonimizado en las interacciones.
    """
    if _checkpointer is None:
        return
    for hilo in hilos:
        await _checkpointer.adelete_thread(hilo)


async def cerrar_checkpointer() -> None:
    global _pool, _checkpointer
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None


# Preguntar dos veces es atender; preguntar cinco es un laberinto.
MAX_VUELTAS_SIN_DEFINIR = 2

def _sin_definir(state: AgentState) -> bool:
    """No sabemos de qué se trata: ni el tipo ni la confianza alcanzan.

    "otro" no es un tipo de caso: si se abre un caso igual, cae en "consulta"
    por defecto y el panel termina mostrando reclamos etiquetados como
    consultas."""
    if state["intencion"] == "otro":
        return True
    return state["confianza"] < settings.agente_umbral_confianza


def decidir_ruta(state: AgentState) -> str:
    # Una clave o una tarjeta no llega a nadie, ni al modelo ni a un operador:
    # el ejecutor contesta con un texto fijo, antes de cualquier otra decisión.
    if ofrece_dato_sensible(state.get("mensaje")):
        return "ejecutor"

    # Cancelar o cambiar un turno no depende de cómo lo clasifique el intake ni
    # de que el caso abierto esté con una persona: lo resuelve el ejecutor por
    # código y actúa sobre la reserva, no sobre el caso de la conversación.
    if state.get("ciudadano_id") is not None and es_gestion_de_turno(state):
        return "ejecutor"

    # El caso ya lo tiene una persona: el agente acusa recibo y se corre. Va
    # primero que todo, incluido un pedido de humano —volver a pasar por
    # `escalado` regeneraría el `resumen_ia` con el que el operador está
    # trabajando— e incluido el saludo.
    #
    # Lo del saludo se aprendió mal: con este chequeo abajo, un "OK, gracias
    # por avisar" contestando al operador se iba por `saludo`, que descarta el
    # caso_id, y el mensaje no quedaba registrado en ninguna parte. El
    # ciudadano recibía el saludo genérico ofreciéndole tomar un reclamo y el
    # operador nunca se enteraba de que le habían contestado.
    if state.get("en_manos_humanas"):
        return "espera"

    # Antes que cualquier otra decisión que dependa de la intención: lo que
    # trae es la respuesta al pedido de datos, y eso lo resuelve el ejecutor.
    if state.get("ciudadano_id") is not None and responde_con_su_identidad(
        bool(state.get("identificado")), state.get("mensaje")
    ):
        return "ejecutor"

    # Pedir hablar con una persona gana sobre el saludo. El clasificador llegó a
    # etiquetar "quisiera hablar con un operador" como saludo, y ahí el
    # ciudadano recibía el "¿en qué puedo ayudarlo?" en vez de que lo derivaran.
    # No se confía en la etiqueta: se mira el pedido explícito.
    if state.get("requiere_escalado"):
        return "escalado"

    # Un saludo no abre caso ni molesta a un operador: se contesta y listo.
    if state["intencion"] == "saludo":
        return "saludo"

    # Sin ciudadano identificado no se pueden ejecutar tools sobre la DB.
    if state.get("ciudadano_id") is None:
        return "escalado"

    # No se entiende qué necesita: se pregunta en vez de derivar. Con tope, que
    # el que no logra explicarse con el agente es justo el que necesita una
    # persona.
    if _sin_definir(state):
        if state.get("vueltas_sin_definir", 0) >= MAX_VUELTAS_SIN_DEFINIR:
            return "escalado"
        return "opciones"

    # "tramite" escala hasta que exista su tool (fase posterior).
    if state["intencion"] == "tramite":
        return "escalado"
    return "ejecutor"


def _decidir_post_ejecutor(state: AgentState) -> str:
    return "escalado" if state.get("requiere_escalado") else END


def _entendido(resultado: dict) -> dict:
    """Marca que este mensaje sí se entendió: pone el contador de repreguntas en
    cero. Hace falta porque `vueltas_sin_definir` sobrevive en el checkpoint del
    hilo provisional (`pre:canal:identificador`), que el ciudadano reusa cada vez
    que arranca sin caso abierto. Sin este reset, dos repreguntas de hace una
    semana lo dejarían derivando al primer mensaje para siempre."""
    return {"vueltas_sin_definir": 0, **resultado}


def construir_grafo(db: AsyncSession, checkpointer: BaseCheckpointSaver | None = None):
    async def _intake(state: AgentState) -> dict:
        return await nodo_intake(state, db)

    async def _contexto(state: AgentState) -> dict:
        return await nodo_contexto(state, db)

    async def _ejecutor(state: AgentState) -> dict:
        return _entendido(await nodo_ejecutor(state, db))

    async def _escalado(state: AgentState) -> dict:
        return _entendido(await nodo_escalado(state, db))

    async def _espera(state: AgentState) -> dict:
        return _entendido(await nodo_espera(state, db))

    async def _saludo(state: AgentState) -> dict:
        return _entendido(await nodo_saludo(state, db))

    grafo = StateGraph(AgentState)
    grafo.add_node("intake", _intake)
    grafo.add_node("contexto", _contexto)
    grafo.add_node("ejecutor", _ejecutor)
    grafo.add_node("escalado", _escalado)
    grafo.add_node("espera", _espera)
    grafo.add_node("saludo", _saludo)
    grafo.add_node("opciones", nodo_opciones)

    grafo.add_edge(START, "intake")
    grafo.add_edge("intake", "contexto")
    grafo.add_conditional_edges(
        "contexto",
        decidir_ruta,
        {
            "ejecutor": "ejecutor",
            "escalado": "escalado",
            "saludo": "saludo",
            "espera": "espera",
            "opciones": "opciones",
        },
    )
    grafo.add_conditional_edges(
        "ejecutor", _decidir_post_ejecutor, {"escalado": "escalado", END: END}
    )
    grafo.add_edge("saludo", END)
    grafo.add_edge("opciones", END)
    grafo.add_edge("escalado", END)
    grafo.add_edge("espera", END)

    return grafo.compile(checkpointer=checkpointer)


def _estado_inicial(mensaje: str, canal: Canal, identificador: str) -> AgentState:
    return {
        "mensaje": mensaje,
        "canal": canal.value,
        "identificador": identificador,
        "ciudadano_id": None,
        "identificado": False,
        "caso_id": None,
        "en_manos_humanas": False,
        "historial": [],
        "conocimiento": [],
        "pautas": [],
        "intencion": None,
        "continua_caso_abierto": True,
        "entidades": {},
        "confianza": 0.0,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
        "tipo_sin_definir": False,
        "caso_elegido": None,
        "origen_menu": None,
        # `vueltas_sin_definir` y `ofertas` se omiten a propósito: lo que no
        # viene en el input conserva el valor del checkpoint. Es la única forma
        # de contar repreguntas y de recordar qué número era cada opción cuando
        # todavía no hay caso donde registrarlo. Los nodos que sí entienden el
        # pedido reinician el contador.
    }


async def _resolver_thread_id(db: AsyncSession, canal: Canal, identificador: str) -> str:
    """thread_id = caso_id (continuidad cross-canal). Si el ciudadano todavía no
    tiene caso activo, se usa un thread provisional por canal+identificador."""
    ciudadano = await obtener_ciudadano_por_canal(db, canal, identificador)
    if ciudadano is not None:
        caso = await obtener_caso_activo_de_ciudadano(db, ciudadano.id)
        if caso is not None:
            return str(caso.id)
    return f"pre:{canal.value}:{identificador}"


# El intake puede clasificar como "otro", que no es un tipo de caso: cae en consulta.
TIPO_POR_INTENCION = {
    "consulta": TipoCaso.consulta,
    "reclamo": TipoCaso.reclamo,
    "reserva": TipoCaso.reserva,
    "tramite": TipoCaso.tramite,
}


async def _abrir_caso(db: AsyncSession, final: AgentState) -> str | None:
    """Un saludo no es una unidad de gestión: no abre caso."""
    """Abre el caso del primer contacto, cuando ninguna tool lo creó.

    Las tools crean el caso al resolver algo, pero una conversación bien puede
    empezar con una pregunta que todavía no ejecuta ninguna: "quiero un turno",
    sin decir para cuándo. Sin esta apertura ese intercambio no quedaba
    registrado en ningún lado —ni el mensaje del ciudadano, ni la respuesta del
    agente, ni la auditoría—, y el contacto se perdía entero.
    """
    ciudadano_id = final.get("ciudadano_id")
    if ciudadano_id is None or final.get("intencion") == "saludo":
        return None
    # Mientras no esté claro de qué se trata no se abre caso: el tipo saldría de
    # una adivinanza y el default es "consulta", que es como los reclamos
    # terminaban etiquetados mal.
    if final.get("tipo_sin_definir"):
        return None

    canal = Canal(final["canal"])
    caso = Caso(
        ciudadano_id=uuid.UUID(ciudadano_id),
        tipo=TIPO_POR_INTENCION.get(final.get("intencion") or "", TipoCaso.consulta),
        canal_origen=canal,
        canal_actual=canal,
    )
    db.add(caso)
    await db.flush()
    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="apertura_caso",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"intencion": final.get("intencion"), "canal": canal.value},
    )
    logger.info("caso abierto en el primer contacto por %s", canal.value)
    return str(caso.id)


async def _persistir_resultado(db: AsyncSession, final: AgentState) -> None:
    caso_id = final.get("caso_id") or await _abrir_caso(db, final)
    if caso_id is None:
        final["respuesta"] = con_aviso_de_seguridad(final["mensaje"], final.get("respuesta"))
        return
    # Que el canal reciba el id: la respuesta al ciudadano lo referencia.
    final["caso_id"] = caso_id

    caso_uuid = uuid.UUID(caso_id)
    canal = Canal(final["canal"])

    # El ciudadano puede retomar un caso desde otro canal: dejar registro del
    # cambio es la evidencia auditable de la continuidad cross-canal.
    caso = await db.get(Caso, caso_uuid)
    if caso is not None and caso.canal_actual != canal:
        canal_anterior = caso.canal_actual
        caso.canal_actual = canal
        await registrar_auditoria(
            db,
            caso_id=caso_uuid,
            accion="cambio_canal",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            metadata={"canal_anterior": canal_anterior.value, "canal_nuevo": canal.value},
        )

    await crear_interaccion(
        db,
        caso_id=caso_uuid,
        contenido=final["mensaje"],
        canal=canal,
        actor=ActorInteraccion.ciudadano,
    )
    if final.get("respuesta"):
        # Antes de persistir y de que el canal lo transmita: el ciudadano tiene
        # que saber que le contesta una IA. Por conversación y canal, no por
        # caso — si va cambiando de tema abre un caso por mensaje.
        final["respuesta"] = await anteponer_aviso(
            db, uuid.UUID(final["ciudadano_id"]), canal, final["respuesta"]
        )
        # Después del aviso de IA, para que quede primero: quien cuenta una
        # emergencia tiene que leer el número antes que cualquier otra cosa.
        # Va acá y no en el ejecutor porque también cubre las derivaciones y
        # la falla del modelo.
        final["respuesta"] = con_aviso_de_seguridad(final["mensaje"], final["respuesta"])
        await crear_interaccion(
            db,
            caso_id=caso_uuid,
            contenido=final["respuesta"],
            canal=canal,
            actor=ActorInteraccion.agente_ia,
        )
    await registrar_auditoria(
        db,
        caso_id=caso_uuid,
        accion="respuesta_ia",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={
            "intencion": final.get("intencion"),
            "confianza": final.get("confianza"),
            "escalado": bool(final.get("requiere_escalado")),
        },
    )
    await db.commit()


async def _derivar_por_falla(
    db: AsyncSession, estado: AgentState, canal: Canal, identificador: str
) -> AgentState:
    """Deriva el mensaje a un operador sin pasar por el modelo.

    Reusa el nodo de escalado, que ya tolera que el modelo no esté: si no puede
    generar el resumen, deja el mensaje original para el operador.
    """
    ciudadano = await obtener_ciudadano_por_canal(db, canal, identificador)
    caso = await obtener_caso_activo_de_ciudadano(db, ciudadano.id) if ciudadano else None
    derivado: AgentState = {
        **estado,
        "ciudadano_id": str(ciudadano.id) if ciudadano else None,
        "caso_id": str(caso.id) if caso else None,
        "requiere_escalado": True,
        "motivo_escalado": "falla_tecnica",
    }
    if ciudadano is None:
        return {**derivado, "respuesta": mensaje_escalado("falla_tecnica", canal=canal)}
    return {**derivado, **await nodo_escalado(derivado, db)}


async def procesar_mensaje(
    db: AsyncSession,
    *,
    mensaje: str,
    canal: Canal,
    identificador: str,
    checkpointer: BaseCheckpointSaver | None = None,
) -> AgentState:
    """Entry point del orquestador: resuelve el thread, corre el grafo y
    persiste interacciones + auditoría de la respuesta."""
    saver = checkpointer if checkpointer is not None else _checkpointer
    if saver is None:
        raise RuntimeError(
            "El checkpointer no está inicializado: falta llamar a iniciar_checkpointer()"
        )

    thread_id = await _resolver_thread_id(db, canal, identificador)
    estado = _estado_inicial(mensaje, canal, identificador)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    grafo = construir_grafo(db, saver)
    try:
        final: AgentState = await grafo.ainvoke(estado, config=config)
    except Exception:
        # RNF-02: si el servidor del modelo no responde (caído, sin memoria,
        # con un error), el ciudadano igual tiene que recibir una respuesta.
        # Sin esto la excepción subía hasta el webhook y el mensaje se perdía.
        logger.exception("procesar_mensaje: falló el procesamiento; se deriva el caso a una persona")
        await db.rollback()
        final = await _derivar_por_falla(db, estado, canal, identificador)

    await _persistir_resultado(db, final)
    logger.debug(
        "procesar_mensaje: thread=%s intencion=%s escalado=%s",
        thread_id,
        final.get("intencion"),
        final.get("requiere_escalado"),
    )
    return final
