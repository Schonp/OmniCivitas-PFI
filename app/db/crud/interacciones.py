import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActorInteraccion, Canal, Interaccion

# Un "1" o un "2" sueltos son la respuesta a un menú (ver `app/agents/eleccion.py`),
# no lo que el ciudadano vino a decir. No se importa ese módulo desde acá —esta
# capa no depende de la de agentes— así que el patrón se repite, simplificado:
# alcanza con reconocer el número pelado, no todas las formas de elegir.
_RESPUESTA_DE_MENU = re.compile(r"^\d{1,2}[.)]?$")


async def crear_interaccion(
    db: AsyncSession,
    *,
    caso_id: uuid.UUID,
    contenido: str,
    canal: Canal,
    actor: ActorInteraccion,
    interna: bool = False,
) -> Interaccion:
    """Agrega la interacción a la transacción del caller. No hace commit."""
    interaccion = Interaccion(
        caso_id=caso_id, contenido=contenido, canal=canal, actor=actor, interna=interna
    )
    db.add(interaccion)
    await db.flush()
    return interaccion


async def listar_interacciones_de_caso(
    db: AsyncSession, caso_id: uuid.UUID, *, limite: int = 10, incluir_internas: bool = True
) -> list[Interaccion]:
    """Últimas N interacciones del caso, en orden cronológico.

    `incluir_internas=False` para todo lo que ve el ciudadano: las notas del
    organismo nunca salen por un canal.
    """
    consulta = select(Interaccion).where(Interaccion.caso_id == caso_id)
    if not incluir_internas:
        consulta = consulta.where(Interaccion.interna.is_(False))

    resultado = await db.execute(
        consulta.order_by(Interaccion.timestamp.desc()).limit(limite)
    )
    return list(reversed(resultado.scalars().all()))


async def ultimo_mensaje_del_ciudadano(
    db: AsyncSession, caso_id: uuid.UUID
) -> datetime | None:
    """Momento del último mensaje que escribió el ciudadano en el caso.

    Lo necesita el envío saliente por WhatsApp: la plataforma solo admite
    mensajes libres dentro de las 24 horas siguientes a ese momento.
    """
    consulta = (
        select(Interaccion.timestamp)
        .where(
            Interaccion.caso_id == caso_id,
            Interaccion.actor == ActorInteraccion.ciudadano,
        )
        .order_by(Interaccion.timestamp.desc())
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first()


async def ultimo_mensaje_al_ciudadano(
    db: AsyncSession, caso_id: uuid.UUID
) -> datetime | None:
    """Momento de lo último que el organismo le mandó al ciudadano en el caso.

    Cuenta tanto lo del agente como lo del operador, y deja afuera las notas
    internas, que el ciudadano nunca vio. Lo usa el nodo de espera para no
    repetirle el acuse de recibo a los dos minutos de haberle avisado.
    """
    consulta = (
        select(Interaccion.timestamp)
        .where(
            Interaccion.caso_id == caso_id,
            Interaccion.actor != ActorInteraccion.ciudadano,
            Interaccion.interna.is_(False),
        )
        .order_by(Interaccion.timestamp.desc())
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first()


async def primeros_mensajes_de_casos(
    db: AsyncSession, caso_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """El primer mensaje del ciudadano en cada caso, para titularlo y para
    buscarlo por tema (`app/tools/consultas.py`).

    El saludo le enumera sus pedidos en curso y una referencia sola no le dice
    nada: nadie se acuerda de qué era REC-A6961E4A. Lo que sí reconoce son sus
    propias palabras — pero si el caso arrancó con "1" (eligiendo del menú de
    inicio), ese "1" no sirve como título ni como tema: se salta y se usa el
    primer mensaje que diga algo. Si el caso no tiene otro (fue puro "1", sin
    seguir contando de qué se trataba), se usa igual, para no dejarlo sin nada.
    """
    if not caso_ids:
        return {}

    filas = await db.execute(
        select(Interaccion.caso_id, Interaccion.contenido)
        .where(
            Interaccion.caso_id.in_(caso_ids),
            Interaccion.actor == ActorInteraccion.ciudadano,
            Interaccion.interna.is_(False),
        )
        .order_by(Interaccion.timestamp)
    )

    primeros: dict[uuid.UUID, str] = {}
    de_menu: dict[uuid.UUID, str] = {}
    for caso_id, contenido in filas:
        if caso_id in primeros:
            continue
        if _RESPUESTA_DE_MENU.match(contenido.strip()):
            de_menu.setdefault(caso_id, contenido)
            continue
        primeros[caso_id] = contenido
    for caso_id, contenido in de_menu.items():
        primeros.setdefault(caso_id, contenido)
    return primeros
