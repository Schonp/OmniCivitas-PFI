"""Derechos del titular de los datos (Ley 25.326): acceso, rectificación y supresión.

Los pedidos llegan por cualquier canal y los resuelve un supervisor desde el
panel: el agente no da de baja a nadie por un mensaje, porque cualquiera que
escriba desde un número podría pedir la baja de los datos de otro.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, Caso, Ciudadano, Interaccion

CONTENIDO_SUPRIMIDO = "[Contenido eliminado a pedido del titular de los datos]"
NOMBRE_SUPRIMIDO = "Titular dado de baja"


async def datos_del_titular(db: AsyncSession, ciudadano: Ciudadano) -> dict:
    """Todo lo que el sistema guarda sobre el ciudadano (RF-14)."""
    casos = list(
        (await db.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id).order_by(Caso.created_at)))
        .scalars()
        .all()
    )
    interacciones = list(
        (
            await db.execute(
                select(Interaccion)
                .where(Interaccion.caso_id.in_([c.id for c in casos]), Interaccion.interna.is_(False))
                .order_by(Interaccion.timestamp)
            )
        )
        .scalars()
        .all()
    ) if casos else []
    por_caso: dict[uuid.UUID, list[dict]] = {}
    for i in interacciones:
        por_caso.setdefault(i.caso_id, []).append(
            {"fecha": i.timestamp.isoformat(), "canal": i.canal.value, "actor": i.actor.value, "contenido": i.contenido}
        )
    return {
        "titular": {
            "nombre": ciudadano.nombre,
            "documento": ciudadano.documento,
            "email": ciudadano.email,
            "telefono": ciudadano.telefono,
            "alta": ciudadano.created_at.isoformat(),
        },
        "finalidad": "Gestionar las consultas, reclamos, reservas y trámites que el titular inicia ante el organismo.",
        "casos": [
            {
                "referencia": c.referencia,
                "tipo": c.tipo.value,
                "estado": c.estado.value,
                "canal_origen": c.canal_origen.value,
                "creado": c.created_at.isoformat(),
                "interacciones": por_caso.get(c.id, []),
            }
            for c in casos
        ],
    }


async def rectificar_titular(
    db: AsyncSession,
    ciudadano: Ciudadano,
    *,
    actor: str,
    nombre: str | None = None,
    email: str | None = None,
    telefono: str | None = None,
) -> Ciudadano:
    """Corrige los datos personales que el titular indica (RF-14)."""
    cambios = []
    if nombre is not None and nombre.strip() and nombre.strip() != ciudadano.nombre:
        ciudadano.nombre = nombre.strip()
        cambios.append("nombre")
    if email is not None and email.strip().lower() != (ciudadano.email or ""):
        ciudadano.email = email.strip().lower() or None
        cambios.append("email")
    if telefono is not None and telefono.strip() != (ciudadano.telefono or ""):
        ciudadano.telefono = telefono.strip() or None
        cambios.append("telefono")
    if cambios:
        # El dato rectificado no va a la auditoría: solo qué campos cambiaron.
        for caso_id in (await db.execute(select(Caso.id).where(Caso.ciudadano_id == ciudadano.id))).scalars():
            await registrar_auditoria(
                db,
                caso_id=caso_id,
                accion="rectificacion_datos_titular",
                actor=actor,
                actor_tipo=ActorInteraccion.operador,
                metadata={"campos": cambios},
            )
    await db.commit()
    await db.refresh(ciudadano)
    return ciudadano


async def dar_de_baja_titular(db: AsyncSession, ciudadano: Ciudadano, *, actor: str) -> list[str]:
    """Suprime los datos personales del titular y anonimiza su historial (RF-13).

    Los casos y la auditoría se conservan: el organismo necesita poder
    demostrar qué hizo con cada pedido, y ninguno de los dos guarda el
    contenido de la conversación. Lo que se borra es todo lo que identifica a
    la persona o reproduce lo que dijo. Devuelve los hilos de conversación del
    orquestador que hay que borrar, porque también guardan los mensajes.
    """
    hilos = []
    if ciudadano.telefono:
        hilos += [f"pre:whatsapp:{ciudadano.telefono}", f"pre:voz:{ciudadano.telefono}"]
    if ciudadano.email:
        hilos.append(f"pre:email:{ciudadano.email}")

    casos = list((await db.execute(select(Caso.id).where(Caso.ciudadano_id == ciudadano.id))).scalars())
    hilos += [str(c) for c in casos]
    if casos:
        await db.execute(
            update(Interaccion).where(Interaccion.caso_id.in_(casos)).values(contenido=CONTENIDO_SUPRIMIDO)
        )
        await db.execute(
            update(Caso).where(Caso.id.in_(casos)).values(resumen_ia=None, asunto=None)
        )
        for caso_id in casos:
            await registrar_auditoria(
                db,
                caso_id=caso_id,
                accion="baja_datos_titular",
                actor=actor,
                actor_tipo=ActorInteraccion.operador,
                metadata={},
            )

    ciudadano.nombre = NOMBRE_SUPRIMIDO
    ciudadano.documento = f"BAJA-{uuid.uuid4().hex[:12]}"
    ciudadano.email = None
    ciudadano.telefono = None
    await db.commit()
    return hilos
