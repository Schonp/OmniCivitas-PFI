import uuid

from langchain_core.tools import ToolException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.tools import ACTOR_AGENTE


async def crear_reserva(
    db: AsyncSession,
    *,
    ciudadano_id: uuid.UUID,
    canal: Canal,
    descripcion: str,
    fecha_solicitada: str,
) -> dict:
    if await obtener_ciudadano_por_id(db, ciudadano_id) is None:
        raise ToolException("Ciudadano no encontrado")

    caso = Caso(
        ciudadano_id=ciudadano_id,
        tipo=TipoCaso.reserva,
        canal_origen=canal,
        canal_actual=canal,
    )
    db.add(caso)
    await db.flush()

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="creacion_reserva",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"fecha_solicitada": fecha_solicitada},
    )
    await db.commit()
    await db.refresh(caso)

    return {
        "caso_id": str(caso.id),
        "tipo": caso.tipo.value,
        "estado": caso.estado.value,
        "fecha_solicitada": fecha_solicitada,
    }
