import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import crear_interaccion
from app.db.models import (
    ActorInteraccion,
    Canal,
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


async def obtener_caso_activo_de_ciudadano(
    db: AsyncSession, ciudadano_id: uuid.UUID
) -> Caso | None:
    """El caso vigente del ciudadano: el último que todavía no se cerró.

    Activo es todo lo que no está `cerrado`, `escalado` incluido. La consulta
    listaba solo `abierto` y `en_progreso`, y `escalado` significa "derivado,
    esperando que alguien lo tome": el caso sigue vivo. Con ese filtro, cuando
    el ciudadano contestaba después de una derivación no se encontraba su caso
    y el mensaje abría uno nuevo, con la conversación partida en dos y el
    operador respondiendo sobre un hilo que el ciudadano ya no estaba usando.
    """
    consulta = (
        select(Caso)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Caso.estado != EstadoCaso.cerrado,
        )
        .order_by(Caso.updated_at.desc())
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first()


async def listar_casos_activos_de_ciudadano(
    db: AsyncSession, ciudadano_id: uuid.UUID, *, limite: int = 5
) -> list[Caso]:
    """Los casos que el ciudadano todavía tiene en curso, del más reciente al
    más viejo. El saludo se los enumera para que pueda retomar uno en vez de
    arrancar otro pedido por lo mismo."""
    consulta = (
        select(Caso)
        .where(
            Caso.ciudadano_id == ciudadano_id,
            Caso.estado != EstadoCaso.cerrado,
        )
        .order_by(Caso.updated_at.desc())
        .limit(limite)
    )
    return list((await db.execute(consulta)).scalars().all())


async def listar_casos_por_ids(db: AsyncSession, ids: list[uuid.UUID]) -> list[Caso]:
    if not ids:
        return []
    consulta = _con_relaciones(select(Caso)).where(Caso.id.in_(ids))
    return list((await db.execute(consulta)).scalars().all())


async def listar_casos_de_ciudadano(db: AsyncSession, ciudadano_id: uuid.UUID) -> list[Caso]:
    """Todos sus casos, cerrados incluidos, del más reciente al más viejo."""
    consulta = (
        _con_relaciones(select(Caso))
        .where(Caso.ciudadano_id == ciudadano_id)
        .order_by(Caso.created_at.desc())
    )
    return list((await db.execute(consulta)).scalars().all())


def _filtrar_casos(
    consulta,
    *,
    estado: EstadoCaso | None,
    busqueda: str | None,
    operador_id: uuid.UUID | None,
    solo_sin_asignar: bool,
    excluir_estado: EstadoCaso | None = None,
):
    if estado is not None:
        consulta = consulta.where(Caso.estado == estado)
    if excluir_estado is not None:
        consulta = consulta.where(Caso.estado != excluir_estado)
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
    excluir_estado: EstadoCaso | None = None,
) -> int:
    consulta = _filtrar_casos(
        select(func.count(Caso.id)),
        estado=estado,
        busqueda=busqueda,
        operador_id=operador_id,
        solo_sin_asignar=solo_sin_asignar,
        excluir_estado=excluir_estado,
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
    excluir_estado: EstadoCaso | None = None,
    limite: int = 50,
    desplazamiento: int = 0,
) -> list[Caso]:
    consulta = _filtrar_casos(
        _con_relaciones(select(Caso)),
        estado=estado,
        busqueda=busqueda,
        operador_id=operador_id,
        solo_sin_asignar=solo_sin_asignar,
        excluir_estado=excluir_estado,
    )
    consulta = consulta.order_by(Caso.updated_at.desc()).limit(limite).offset(desplazamiento)
    resultado = await db.execute(consulta)
    return list(resultado.scalars().all())


async def esperas_de_casos(
    db: AsyncSession, casos: list[Caso]
) -> dict[uuid.UUID, datetime | None]:
    """Desde cuándo espera respuesta cada caso.

    Es el último mensaje del ciudadano que todavía no tiene una respuesta
    posterior. Si ya le respondieron, no espera nada.

    Qué cuenta como respuesta depende de en manos de quién está el caso: en uno
    derivado o tomado por un operador, lo que se espera es la respuesta de esa
    persona, así que el acuse de recibo del agente no lo saca de la cola. De lo
    contrario el aviso de derivación bastaba para que el caso figurara atendido
    y desapareciera de la bandeja sin que nadie lo hubiera mirado.
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
    ultima_del_operador: dict[uuid.UUID, datetime] = {}
    for caso_id, actor, momento in filas:
        if actor == ActorInteraccion.ciudadano:
            ultimo_ciudadano[caso_id] = momento
        else:
            ultima_respuesta[caso_id] = momento
            if actor == ActorInteraccion.operador:
                ultima_del_operador[caso_id] = momento

    esperas: dict[uuid.UUID, datetime | None] = {}
    for caso in casos:
        consulta = ultimo_ciudadano.get(caso.id)
        respuesta = (
            ultima_del_operador.get(caso.id)
            if caso.en_manos_humanas
            else ultima_respuesta.get(caso.id)
        )
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
    db: AsyncSession,
    caso: Caso,
    operador: Usuario | None,
    *,
    actor: str,
    actor_tipo: ActorInteraccion = ActorInteraccion.operador,
) -> Caso:
    """Asigna el caso a un operador, o lo libera si `operador` es None.

    Tomar un caso lo pone en progreso, y liberarlo lo devuelve a abierto. Antes
    ningún camino del código asignaba `en_progreso`: quedaba a criterio del
    operador ponerlo a mano, así que el estado no reflejaba la realidad. El paso
    por `escalado` no se pierde, queda en la auditoría.

    `actor_tipo` por defecto es `operador` (el panel: alguien tomó o reasignó el
    caso a mano). El escalado automático pasa `agente_ia`, para que la auditoría
    diga quién asignó de verdad y no le atribuya la acción a una persona.
    """
    anterior = caso.operador_asignado
    estado_anterior = caso.estado
    caso.operador_asignado_id = operador.id if operador is not None else None

    if caso.estado != EstadoCaso.cerrado:
        caso.estado = (
            EstadoCaso.en_progreso if operador is not None else EstadoCaso.abierto
        )

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="asignacion",
        actor=actor,
        actor_tipo=actor_tipo,
        metadata={
            "operador_anterior": anterior.nombre if anterior is not None else None,
            "operador_nuevo": operador.nombre if operador is not None else None,
            "estado_anterior": estado_anterior.value,
            "estado_nuevo": caso.estado.value,
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
    db: AsyncSession,
    caso: Caso,
    contenido: str,
    *,
    actor: str,
    interna: bool = False,
    canal: Canal | None = None,
) -> Interaccion:
    """Registra la respuesta del operador como una interacción más del caso.

    Se guarda sobre `canal`, que por defecto es el canal actual del caso. El
    endpoint pasa el canal por el que la respuesta sale de verdad: la de un caso
    de voz se manda por WhatsApp, y así tiene que quedar en la conversación.
    Con `interna=True` es una nota que solo ve el organismo.
    """
    canal = canal or caso.canal_actual
    interaccion = await crear_interaccion(
        db,
        caso_id=caso.id,
        contenido=contenido,
        canal=canal,
        actor=ActorInteraccion.operador,
        interna=interna,
    )

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="nota_interna" if interna else "respuesta_operador",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
        metadata={"canal": canal.value},
    )

    await db.commit()
    await db.refresh(interaccion)
    return interaccion
