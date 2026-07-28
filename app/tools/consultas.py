import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, Caso
from app.tools import ACTOR_AGENTE


async def consultar_estado_caso(db: AsyncSession, *, ciudadano_id: uuid.UUID) -> dict:
    resultado = await db.execute(
        select(Caso)
        .where(Caso.ciudadano_id == ciudadano_id)
        .order_by(Caso.updated_at.desc())
        .limit(1)
    )
    caso = resultado.scalars().first()
    if caso is None:
        return {"tiene_casos": False, "mensaje": "El ciudadano no tiene casos registrados."}

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="consulta_estado",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
    )
    await db.commit()

    return {
        "tiene_casos": True,
        "caso_id": str(caso.id),
        "tipo": caso.tipo.value,
        "estado": caso.estado.value,
        "actualizado": caso.updated_at.isoformat(),
    }
