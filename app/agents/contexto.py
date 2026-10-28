import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.espera import contacto_reciente
from app.agents.identidad import responde_con_su_identidad
from app.agents.state import AgentState
from app.db.crud.casos import obtener_caso_activo_de_ciudadano, obtener_caso_por_id
from app.db.crud.ciudadanos import (
    esta_identificado,
    obtener_ciudadano_por_email,
    obtener_ciudadano_por_telefono,
)
from app.db.crud.conocimiento import buscar_documentos_relevantes, listar_pautas_generales
from app.db.crud.interacciones import (
    listar_interacciones_de_caso,
    ultimo_mensaje_al_ciudadano,
)
from app.db.crud.turnos import horario_de_atencion, listar_agendas
from app.db.models import Canal, Ciudadano

logger = logging.getLogger(__name__)

HISTORIAL_MAX_INTERACCIONES = 10


async def obtener_ciudadano_por_canal(
    db: AsyncSession, canal: Canal, identificador: str
) -> Ciudadano | None:
    if canal in (Canal.whatsapp, Canal.voz):
        return await obtener_ciudadano_por_telefono(db, identificador)
    return await obtener_ciudadano_por_email(db, identificador)


async def buscar_conocimiento(
    db: AsyncSession, intencion: str | None, mensaje: str
) -> list[str]:
    """Contexto del organismo para el ejecutor: documentos de la base de
    conocimiento que mencionan palabras del mensaje (recuperación léxica, ver
    buscar_documentos_relevantes) y, si la intención es reservar, las agendas
    de turnos disponibles para que la tool reciba un nombre válido."""
    conocimiento = await buscar_documentos_relevantes(db, mensaje)

    if intencion == "reserva":
        agendas = await listar_agendas(db)
        if agendas:
            # La primera línea es la misma con la que se entrenó el modelo; la
            # segunda le da la grilla, para que proponga horarios que existen.
            conocimiento.append(
                "Turnos disponibles para reservar: " + "; ".join(a.nombre for a in agendas)
            )
            conocimiento.append(
                "Horarios de atención: "
                + "; ".join(f"{a.nombre}, {horario_de_atencion(a)}" for a in agendas)
            )

    return conocimiento


async def nodo_contexto(state: AgentState, db: AsyncSession) -> dict:
    ciudadano = await obtener_ciudadano_por_canal(
        db, Canal(state["canal"]), state["identificador"]
    )
    if ciudadano is None:
        logger.debug("contexto: ciudadano no identificado por canal %s", state["canal"])
        return {
            "ciudadano_id": None,
            "identificado": False,
            "caso_id": None,
            "en_manos_humanas": False,
            "historial": [],
            "conocimiento": [],
            "pautas": await listar_pautas_generales(db),
        }

    # Un tema nuevo no se pega al caso abierto ni hereda su historial: el
    # ciudadano puede tener un reclamo en curso y preguntar por otra cosa.
    #
    # La excepción es el caso que ya tiene una persona. Ahí todo lo que escriba
    # el ciudadano es parte de esa conversación —cambie de tema, insista o
    # agradezca— y le corresponde al operador. Si no se busca el caso también
    # en ese camino, el mensaje se queda sin caso al que colgarse y termina
    # descartado sin que nadie se entere.
    elegido = state.get("caso_elegido")
    activo = (
        # Lo eligió por número en el menú: no hay nada que inferir.
        await obtener_caso_por_id(db, uuid.UUID(elegido))
        if elegido
        else await obtener_caso_activo_de_ciudadano(db, ciudadano.id)
    )

    # ¿Este mensaje es parte del caso que ya venía?
    #
    # Para una cortesía lo decide el tiempo y no el intake: "gracias" un minuto
    # después de que el operador contestó es parte del hilo, y "hola" tres días
    # más tarde es una conversación nueva. Sin esa distinción, un caso derivado
    # que nadie tomó se queda con todos los saludos que vengan después y el
    # ciudadano no vuelve a hablar con el agente nunca más.
    if state.get("intencion") == "saludo":
        pertenece_al_hilo = activo is not None and contacto_reciente(
            await ultimo_mensaje_al_ciudadano(db, activo.id)
        )
    elif responde_con_su_identidad(esta_identificado(ciudadano), state.get("mensaje")):
        # Es la respuesta al pedido de nombre y DNI: el pedido que la motivó
        # está en el caso abierto. Si el intake lo toma como tema nuevo, se
        # abre otro caso con el nombre y el DNI como descripción.
        pertenece_al_hilo = True
    else:
        # Un tema nuevo no se pega al caso abierto ni hereda su historial: el
        # ciudadano puede tener un reclamo en curso y preguntar por otra cosa.
        pertenece_al_hilo = state.get("continua_caso_abierto", True)

    en_manos_humanas = (
        activo is not None and activo.en_manos_humanas and pertenece_al_hilo
    )
    caso = activo if pertenece_al_hilo else None
    historial: list[dict] = []
    if caso is not None:
        # Sin notas internas: si entraran al contexto, el LLM podría repetirle al
        # ciudadano algo que el organismo anotó para uso propio.
        interacciones = await listar_interacciones_de_caso(
            db, caso.id, limite=HISTORIAL_MAX_INTERACCIONES, incluir_internas=False
        )
        historial = [
            {"actor": i.actor.value, "contenido": i.contenido, "canal": i.canal.value}
            for i in interacciones
        ]

    conocimiento = await buscar_conocimiento(db, state.get("intencion"), state["mensaje"])

    return {
        "ciudadano_id": str(ciudadano.id),
        # Si arrastra el documento provisorio del alta, el ejecutor le va a
        # pedir que se identifique antes de gestionar nada.
        "identificado": esta_identificado(ciudadano),
        "caso_id": str(caso.id) if caso is not None else None,
        # Si el caso ya lo tiene una persona, el router manda a `espera` y el
        # agente no vuelve a intervenir sobre él.
        "en_manos_humanas": en_manos_humanas,
        "historial": historial,
        "conocimiento": conocimiento,
        "pautas": await listar_pautas_generales(db),
    }
