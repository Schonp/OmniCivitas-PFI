import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, Caso, EstadoCaso
from app.schemas.caso import CasoCreate


async def obtener_caso_por_id(db: AsyncSession, caso_id: uuid.UUID) -> Caso | None:
    return await db.get(Caso, caso_id)


async def listar_casos(db: AsyncSession, *, estado: EstadoCaso | None = None) -> list[Caso]:
    consulta = select(Caso).order_by(Caso.created_at.desc())
    if estado is not None:
        consulta = consulta.where(Caso.estado == estado)
    resultado = await db.execute(consulta)
    return list(resultado.scalars().all())


async def crear_caso(db: AsyncSession, datos: CasoCreate, *, actor: str) -> Caso:
    caso = Caso(
        ciudadano_id=datos.ciudadano_id,
        tipo=datos.tipo,
        canal_origen=datos.canal_origen,
        canal_actual=datos.canal_origen,
    )
    db.add(caso)
    await db.flush()

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="creacion",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
    )

    await db.commit()
    await db.refresh(caso)
    return caso


async def cambiar_estado_caso(
    db: AsyncSession, caso: Caso, nuevo_estado: EstadoCaso, *, actor: str
) -> Caso:
    estado_anterior = caso.estado
    caso.estado = nuevo_estado

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="cambio_estado",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={"estado_anterior": estado_anterior.value, "estado_nuevo": nuevo_estado.value},
    )

    await db.commit()
    await db.refresh(caso)
    return caso
