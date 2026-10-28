import uuid
from datetime import datetime

from langchain_core.tools import ToolException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.crud.turnos import (
    ZONA_HORARIA,
    listar_nombres_de_turnos,
    obtener_turno_por_nombre,
    reservar,
)
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.tools import ACTOR_AGENTE

FORMATO_FECHA_HORA = "%Y-%m-%d %H:%M"


def leer_fecha_hora(fecha_hora: str) -> datetime:
    """"2026-11-05 10:00" es la hora que dijo el ciudadano, en Argentina.

    Antes se guardaba como si fuera UTC: el turno de las 10 aparecía en el panel
    a las 7.
    """
    try:
        return datetime.strptime(fecha_hora, FORMATO_FECHA_HORA).replace(tzinfo=ZONA_HORARIA)
    except ValueError as error:
        raise ToolException("fecha_hora inválida: usar el formato AAAA-MM-DD HH:MM") from error


async def crear_reserva(
    db: AsyncSession,
    *,
    ciudadano_id: uuid.UUID,
    canal: Canal,
    turno: str,
    fecha_hora: str,
    caso_id: uuid.UUID | None = None,
) -> dict:
    """Reserva el turno o levanta `ReservaNoDisponible` con los horarios libres
    más cercanos, que el ejecutor le ofrece al ciudadano sin pasar por el modelo."""
    if await obtener_ciudadano_por_id(db, ciudadano_id) is None:
        raise ToolException("Ciudadano no encontrado")

    agenda = await obtener_turno_por_nombre(db, turno)
    if agenda is None:
        disponibles = ", ".join(await listar_nombres_de_turnos(db))
        raise ToolException(
            f"No existe un turno que coincida con '{turno}'. Turnos disponibles: {disponibles}"
        )
    momento = leer_fecha_hora(fecha_hora)

    # Si el horario no se puede reservar, el caso que se abriría para la
    # reserva tampoco tiene que quedar: todo va en un mismo savepoint.
    async with db.begin_nested():
        # Igual que en `crear_reclamo`: si la conversación ya tenía un caso
        # abierto para esta reserva (se abrió al pedir el turno, antes de tener
        # día y horario), se completa ese caso en vez de abrir uno nuevo.
        caso = await db.get(Caso, caso_id) if caso_id is not None else None
        if caso is None or caso.tipo != TipoCaso.reserva:
            caso = Caso(
                ciudadano_id=ciudadano_id,
                tipo=TipoCaso.reserva,
                canal_origen=canal,
                canal_actual=canal,
            )
            db.add(caso)
            await db.flush()

        reserva = await reservar(
            db, agenda_id=agenda.id, ciudadano_id=ciudadano_id, caso_id=caso.id, momento=momento
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
        "referencia": caso.referencia,
        "caso_id": str(caso.id),
        "reserva_id": str(reserva.id),
        "turno": agenda.nombre,
        "fecha_hora": fecha_hora,
        "sede": agenda.sede,
        "estado": caso.estado.value,
    }
