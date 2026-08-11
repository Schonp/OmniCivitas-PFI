import uuid
from datetime import datetime, timezone

from langchain_core.tools import ToolException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.crud.turnos import (
    crear_reserva_de_turno,
    listar_nombres_de_turnos,
    obtener_turno_por_nombre,
)
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.tools import ACTOR_AGENTE

FORMATO_FECHA_HORA = "%Y-%m-%d %H:%M"


async def crear_reserva(
    db: AsyncSession,
    *,
    ciudadano_id: uuid.UUID,
    canal: Canal,
    turno: str,
    fecha_hora: str,
) -> dict:
    if await obtener_ciudadano_por_id(db, ciudadano_id) is None:
        raise ToolException("Ciudadano no encontrado")

    agenda = await obtener_turno_por_nombre(db, turno)
    if agenda is None:
        disponibles = ", ".join(await listar_nombres_de_turnos(db))
        raise ToolException(
            f"No existe un turno que coincida con '{turno}'. Turnos disponibles: {disponibles}"
        )

    try:
        momento = datetime.strptime(fecha_hora, FORMATO_FECHA_HORA).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ToolException(
            "fecha_hora inválida: usar el formato AAAA-MM-DD HH:MM"
        ) from error

    caso = Caso(
        ciudadano_id=ciudadano_id,
        tipo=TipoCaso.reserva,
        canal_origen=canal,
        canal_actual=canal,
    )
    db.add(caso)
    await db.flush()

    reserva = await crear_reserva_de_turno(
        db,
        turno_id=agenda.id,
        caso_id=caso.id,
        ciudadano_id=ciudadano_id,
        fecha_hora=momento,
    )

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="creacion_reserva",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"turno": agenda.nombre, "fecha_hora": fecha_hora},
    )
    await db.commit()
    await db.refresh(caso)

    return {
        "caso_id": str(caso.id),
        "reserva_id": str(reserva.id),
        "turno": agenda.nombre,
        "fecha_hora": fecha_hora,
        "estado": caso.estado.value,
    }
