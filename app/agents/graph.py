import logging
import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contexto import nodo_contexto, obtener_ciudadano_por_canal
from app.agents.ejecutor import nodo_ejecutor
from app.agents.escalado import nodo_escalado
from app.agents.intake import nodo_intake
from app.agents.state import AgentState
from app.core.config import settings
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.casos import obtener_caso_abierto_de_ciudadano
from app.db.crud.interacciones import crear_interaccion
from app.db.models import ActorInteraccion, Canal, Caso
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


async def cerrar_checkpointer() -> None:
    global _pool, _checkpointer
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None


def decidir_ruta(state: AgentState) -> str:
    if state["confianza"] < settings.agente_umbral_confianza:
        return "escalado"
    if state.get("requiere_escalado"):
        return "escalado"
    # "tramite" escala hasta que exista su tool (fase posterior).
    if state["intencion"] in ("otro", "tramite"):
        return "escalado"
    # Sin ciudadano identificado no se pueden ejecutar tools sobre la DB.
    if state.get("ciudadano_id") is None:
        return "escalado"
    return "ejecutor"


def _decidir_post_ejecutor(state: AgentState) -> str:
    return "escalado" if state.get("requiere_escalado") else END


def construir_grafo(db: AsyncSession, checkpointer: BaseCheckpointSaver | None = None):
    async def _contexto(state: AgentState) -> dict:
        return await nodo_contexto(state, db)

    async def _ejecutor(state: AgentState) -> dict:
        return await nodo_ejecutor(state, db)

    async def _escalado(state: AgentState) -> dict:
        return await nodo_escalado(state, db)

    grafo = StateGraph(AgentState)
    grafo.add_node("intake", nodo_intake)
    grafo.add_node("contexto", _contexto)
    grafo.add_node("ejecutor", _ejecutor)
    grafo.add_node("escalado", _escalado)

    grafo.add_edge(START, "intake")
    grafo.add_edge("intake", "contexto")
    grafo.add_conditional_edges(
        "contexto", decidir_ruta, {"ejecutor": "ejecutor", "escalado": "escalado"}
    )
    grafo.add_conditional_edges(
        "ejecutor", _decidir_post_ejecutor, {"escalado": "escalado", END: END}
    )
    grafo.add_edge("escalado", END)

    return grafo.compile(checkpointer=checkpointer)


def _estado_inicial(mensaje: str, canal: Canal, identificador: str) -> AgentState:
    return {
        "mensaje": mensaje,
        "canal": canal.value,
        "identificador": identificador,
        "ciudadano_id": None,
        "caso_id": None,
        "historial": [],
        "conocimiento": [],
        "intencion": None,
        "entidades": {},
        "confianza": 0.0,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }


async def _resolver_thread_id(db: AsyncSession, canal: Canal, identificador: str) -> str:
    """thread_id = caso_id (continuidad cross-canal). Si el ciudadano todavía no
    tiene caso abierto, se usa un thread provisional por canal+identificador."""
    ciudadano = await obtener_ciudadano_por_canal(db, canal, identificador)
    if ciudadano is not None:
        caso = await obtener_caso_abierto_de_ciudadano(db, ciudadano.id)
        if caso is not None:
            return str(caso.id)
    return f"pre:{canal.value}:{identificador}"


async def _persistir_resultado(db: AsyncSession, final: AgentState) -> None:
    caso_id = final.get("caso_id")
    if caso_id is None:
        return

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
    final: AgentState = await grafo.ainvoke(estado, config=config)

    await _persistir_resultado(db, final)
    logger.debug(
        "procesar_mensaje: thread=%s intencion=%s escalado=%s",
        thread_id,
        final.get("intencion"),
        final.get("requiere_escalado"),
    )
    return final
