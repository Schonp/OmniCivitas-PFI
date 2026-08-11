import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import crear_interaccion
from app.db.models import (
    ActorInteraccion,
    Caso,
    Ciudadano,
    EstadoCaso,
    Interaccion,
    Usuario,
)
from app.schemas.caso import CasoCreate

# El panel muestra el nombre del ciudadano y del operador asignado: en async no
# se pueden resolver las relaciones de forma perezosa al serializar.
_RELACIONES_PANEL = ("ciudadano", "operador_asignado")


def _con_relaciones(consulta):
    return consulta.options(
        selectinload(Caso.ciudadano), selectinload(Caso.operador_asignado)
    )


async def _refrescar_para_panel(db: AsyncSession, caso: Caso) -> None:
    # Primero los defaults del servidor (timestamps), después las relaciones.
    await db.refresh(caso)
    await db.refresh(caso, list(_RELACIONES_PANEL))


async def obtener_caso_por_id(db: AsyncSession, caso_id: uuid.UUID) -> Caso | None:
    consulta = _con_relaciones(select(Caso).where(Caso.id == caso_id))
    return (await db.execute(consulta)).scalars().first()


async def obtener_casos_por_ids(db: AsyncSession, ids: list[uuid.UUID]) -> list[Caso]:
    if not ids:
        return []
    consulta = _con_relaciones(select(Caso).where(Caso.id.in_(ids)))
    return list((await db.execute(consulta)).scalars().all())


async def obtener_caso_abierto_de_ciudadano(
    db: AsyncSession, ciudadano_id: uuid.UUID
) -> Caso | None:
    consulta = (
        select(Caso)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Caso.estado.in_([EstadoCaso.abierto, EstadoCaso.en_progreso]),
        )
        .order_by(Caso.updated_at.desc())
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first()


def _filtrar_casos(
    consulta,
    *,
    estado: EstadoCaso | None,
    busqueda: str | None,
    operador_id: uuid.UUID | None,
    solo_sin_asignar: bool,
):
    if estado is not None:
        consulta = consulta.where(Caso.estado == estado)
    if operador_id is not None:
        consulta = consulta.where(Caso.operador_asignado_id == operador_id)
    if solo_sin_asignar:
        consulta = consulta.where(Caso.operador_asignado_id.is_(None))
    if busqueda:
        patron = f"%{busqueda.strip()}%"
        consulta = consulta.join(Caso.ciudadano).where(
            or_(Ciudadano.nombre.ilike(patron), Ciudadano.documento.ilike(patron))
        )
    return consulta


async def contar_casos(
    db: AsyncSession,
    *,
    estado: EstadoCaso | None = None,
    busqueda: str | None = None,
    operador_id: uuid.UUID | None = None,
    solo_sin_asignar: bool = False,
) -> int:
    consulta = _filtrar_casos(
        select(func.count(Caso.id)),
        estado=estado,
        busqueda=busqueda,
        operador_id=operador_id,
        solo_sin_asignar=solo_sin_asignar,
    )
    return (await db.execute(consulta)).scalar_one()


async def contar_casos_por_estado(
    db: AsyncSession, *, operador_id: uuid.UUID | None = None
) -> dict[str, int]:
    """Casos por estado con la misma visibilidad que la lista: la bandeja del
    operador y sus contadores tienen que contar lo mismo."""
    consulta = select(Caso.estado, func.count(Caso.id)).group_by(Caso.estado)
    if operador_id is not None:
        consulta = consulta.where(Caso.operador_asignado_id == operador_id)
    filas = await db.execute(consulta)
    return {estado.value: cantidad for estado, cantidad in filas}


async def listar_casos(
    db: AsyncSession,
    *,
    estado: EstadoCaso | None = None,
    busqueda: str | None = None,
    operador_id: uuid.UUID | None = None,
    solo_sin_asignar: bool = False,
    limite: int = 50,
    desplazamiento: int = 0,
) -> list[Caso]:
    consulta = _filtrar_casos(
        _con_relaciones(select(Caso)),
        estado=estado,
        busqueda=busqueda,
        operador_id=operador_id,
        solo_sin_asignar=solo_sin_asignar,
    )
    consulta = consulta.order_by(Caso.updated_at.desc()).limit(limite).offset(desplazamiento)
    resultado = await db.execute(consulta)
    return list(resultado.scalars().all())


async def esperas_de_casos(
    db: AsyncSession, casos: list[Caso]
) -> dict[uuid.UUID, datetime | None]:
    """Desde cuándo espera respuesta cada caso.

    Es el último mensaje del ciudadano que todavía no tiene una respuesta
    posterior del agente o del operador. Si ya le respondieron, no espera nada.
    """
    if not casos:
        return {}

    ids = [caso.id for caso in casos]
    filas = await db.execute(
        select(Interaccion.caso_id, Interaccion.actor, Interaccion.timestamp)
        .where(Interaccion.caso_id.in_(ids), Interaccion.interna.is_(False))
        .order_by(Interaccion.timestamp)
    )

    ultimo_ciudadano: dict[uuid.UUID, datetime] = {}
    ultima_respuesta: dict[uuid.UUID, datetime] = {}
    for caso_id, actor, momento in filas:
        if actor == ActorInteraccion.ciudadano:
            ultimo_ciudadano[caso_id] = momento
        else:
            ultima_respuesta[caso_id] = momento

    esperas: dict[uuid.UUID, datetime | None] = {}
    for caso in casos:
        consulta = ultimo_ciudadano.get(caso.id)
        respuesta = ultima_respuesta.get(caso.id)
        sin_responder = consulta is not None and (respuesta is None or respuesta < consulta)
        esperas[caso.id] = consulta if sin_responder else None
    return esperas


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
    await _refrescar_para_panel(db, caso)
    return caso


async def cambiar_estado_caso(
    db: AsyncSession,
    caso: Caso,
    nuevo_estado: EstadoCaso,
    *,
    actor: str,
    motivo: str | None = None,
) -> Caso:
    estado_anterior = caso.estado
    caso.estado = nuevo_estado
    # El motivo tipifica el cierre y alimenta las métricas; si el caso se reabre,
    # deja de aplicar.
    caso.motivo_cierre = motivo if nuevo_estado == EstadoCaso.cerrado else None

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="cambio_estado",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={
            "estado_anterior": estado_anterior.value,
            "estado_nuevo": nuevo_estado.value,
            **({"motivo": motivo} if motivo else {}),
        },
    )

    await db.commit()
    await _refrescar_para_panel(db, caso)
    return caso


async def asignar_caso(
    db: AsyncSession, caso: Caso, operador: Usuario | None, *, actor: str
) -> Caso:
    """Asigna el caso a un operador, o lo libera si `operador` es None."""
    anterior = caso.operador_asignado
    caso.operador_asignado_id = operador.id if operador is not None else None

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="asignacion",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={
            "operador_anterior": anterior.nombre if anterior is not None else None,
            "operador_nuevo": operador.nombre if operador is not None else None,
        },
    )

    await db.commit()
    await _refrescar_para_panel(db, caso)
    return caso


async def actualizar_resumen_caso(
    db: AsyncSession, caso: Caso, resumen: str, *, actor: str
) -> Caso:
    """Persiste el resumen generado por IA y deja rastro de quién lo pidió."""
    caso.resumen_ia = resumen
    caso.resumen_ia_generado_en = datetime.now(timezone.utc)

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="resumen_ia",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={"resumen": resumen},
    )

    await db.commit()
    await _refrescar_para_panel(db, caso)
    return caso


async def responder_caso(
    db: AsyncSession, caso: Caso, contenido: str, *, actor: str, interna: bool = False
) -> Interaccion:
    """Registra la respuesta del operador como una interacción más del caso.

    Se guarda sobre el canal actual del caso: el ciudadano la ve al consultar su
    conversación. El envío saliente por WhatsApp/email llega con esos canales.
    Con `interna=True` es una nota que solo ve el organismo.
    """
    interaccion = await crear_interaccion(
        db,
        caso_id=caso.id,
        contenido=contenido,
        canal=caso.canal_actual,
        actor=ActorInteraccion.operador,
        interna=interna,
    )

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="nota_interna" if interna else "respuesta_operador",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={"canal": caso.canal_actual.value},
    )

    await db.commit()
    await db.refresh(interaccion)
    return interaccion
