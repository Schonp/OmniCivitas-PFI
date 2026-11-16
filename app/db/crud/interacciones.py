import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActorInteraccion, Canal, Caso, Interaccion

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


async def ultimo_mensaje_por_whatsapp(
    db: AsyncSession, ciudadano_id: uuid.UUID
) -> datetime | None:
    """Momento del último mensaje que el ciudadano mandó por WhatsApp.

    Lo necesita el envío saliente por WhatsApp: la plataforma solo admite
    mensajes libres dentro de las 24 horas siguientes a ese momento. Se mira
    cualquier caso del ciudadano y solo sus mensajes por WhatsApp, porque la
    ventana es de la conversación con ese número, no del caso: un turno de una
    llamada no la abre, y un mensaje de WhatsApp en otro caso sí.
    """
    consulta = (
        select(Interaccion.timestamp)
        .join(Caso, Interaccion.caso_id == Caso.id)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Interaccion.actor == ActorInteraccion.ciudadano,
            Interaccion.canal == Canal.whatsapp,
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
    internas, que el ciudadano nunca vio. Lo usa el agente de contexto para
    decidir si una cortesía sigue el hilo del caso; el nodo de espera usa
    `ultimo_saliente_con_canal`, porque además le importa el canal.
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


async def ultimo_saliente_con_canal(
    db: AsyncSession, caso_id: uuid.UUID
) -> tuple[datetime, Canal] | None:
    """Lo último que el organismo le mandó al ciudadano en el caso, con el canal
    por el que salió.

    Mismo criterio que `ultimo_mensaje_al_ciudadano` (agente u operador, sin
    notas internas), pero el nodo de espera necesita además el canal: un aviso
    que salió por la llamada no lo vio en el chat de WhatsApp.
    """
    consulta = (
        select(Interaccion.timestamp, Interaccion.canal)
        .where(
            Interaccion.caso_id == caso_id,
            Interaccion.actor != ActorInteraccion.ciudadano,
            Interaccion.interna.is_(False),
        )
        .order_by(Interaccion.timestamp.desc())
        .limit(1)
    )
    fila = (await db.execute(consulta)).first()
    return (fila.timestamp, fila.canal) if fila is not None else None


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


@dataclass
class ActividadCaso:
    mensajes: int
    ultimo: Interaccion | None
    # Los canales por los que pasó la conversación, en el orden en que aparecieron.
    recorrido: list[Canal]


async def actividad_de_casos(
    db: AsyncSession, caso_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ActividadCaso]:
    """Cuántos mensajes tiene cada caso, el último y por qué canales pasó.

    Sin las notas internas: es lo que se conversó con el ciudadano.
    """
    if not caso_ids:
        return {}
    filas = await db.execute(
        select(Interaccion)
        .where(Interaccion.caso_id.in_(caso_ids), Interaccion.interna.is_(False))
        .order_by(Interaccion.timestamp)
    )
    actividad = {caso_id: ActividadCaso(0, None, []) for caso_id in caso_ids}
    for interaccion in filas.scalars():
        del_caso = actividad[interaccion.caso_id]
        del_caso.mensajes += 1
        del_caso.ultimo = interaccion
        if interaccion.canal not in del_caso.recorrido:
            del_caso.recorrido.append(interaccion.canal)
    return actividad
