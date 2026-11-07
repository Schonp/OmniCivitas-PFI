"""Agendas de turnos: la grilla de horarios, la disponibilidad y las reservas.

Todas las reglas de un turnero viven acá y no en el modelo de lenguaje: un
horario solo se puede reservar si existe en la grilla de la agenda, no pasó,
está dentro de la anticipación máxima y le queda cupo. El agente propone un día
y una hora; lo que se reserva lo decide este módulo.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, DiaBloqueado, EstadoReserva, Reserva, Turno

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
# Cuántos horarios libres se le ofrecen al ciudadano cuando el que pidió no está.
ALTERNATIVAS = 3
# Hasta dónde se buscan esas alternativas, contando desde el día pedido.
DIAS_DE_BUSQUEDA = 7


class ReservaNoDisponible(Exception):
    """El horario pedido no se puede reservar.

    `motivo` lo explica en palabras para el ciudadano; `alternativas` trae los
    horarios libres más cercanos, y `vigente`, el turno que ya tiene si el
    problema es que pidió otro del mismo trámite.
    """

    def __init__(
        self,
        motivo: str,
        *,
        alternativas: list[datetime] | None = None,
        vigente: Reserva | None = None,
    ):
        super().__init__(motivo)
        self.motivo = motivo
        self.alternativas = alternativas or []
        self.vigente = vigente


def ahora_local() -> datetime:
    return datetime.now(ZONA_HORARIA)


def _hora(valor: time | datetime) -> str:
    """"8:00", "10:30"."""
    return f"{valor.hour}:{valor.minute:02d}"


def momento_en_palabras(momento: datetime) -> str:
    """"jueves 5 de noviembre a las 10:30"."""
    local = momento.astimezone(ZONA_HORARIA)
    return f"{DIAS_SEMANA[local.weekday()]} {local.day} de {MESES[local.month - 1]} a las {_hora(local)}"


def horario_de_atencion(agenda: Turno) -> str:
    """"de lunes a viernes de 8:00 a 14:00, cada 30 minutos"."""
    dias = agenda.dias
    if len(dias) > 2 and dias == list(range(dias[0], dias[-1] + 1)):
        cuando = f"de {DIAS_SEMANA[dias[0]]} a {DIAS_SEMANA[dias[-1]]}"
    else:
        nombres = [DIAS_SEMANA[d] for d in dias]
        cuando = "los " + (" y ".join([", ".join(nombres[:-1]), nombres[-1]]) if len(nombres) > 1 else nombres[0])
    return (
        f"{cuando} de {_hora(agenda.hora_apertura)} a {_hora(agenda.hora_cierre)}, "
        f"cada {agenda.duracion_minutos} minutos"
    )


def fecha_en_palabras(dia: date) -> str:
    """"jueves 5 de noviembre"."""
    return f"{DIAS_SEMANA[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}"


def horarios_del_dia(
    agenda: Turno, dia: date, bloqueados: dict[date, str] | None = None
) -> list[datetime]:
    """Los horarios de la grilla de ese día, en hora argentina. Un día
    bloqueado (feriado, jornada sin atención) no tiene horarios."""
    if dia.weekday() not in agenda.dias or dia in (bloqueados or {}):
        return []
    paso = timedelta(minutes=agenda.duracion_minutos)
    momento = datetime.combine(dia, agenda.hora_apertura, tzinfo=ZONA_HORARIA)
    cierre = datetime.combine(dia, agenda.hora_cierre, tzinfo=ZONA_HORARIA)
    horarios = []
    while momento + paso <= cierre:
        horarios.append(momento)
        momento += paso
    return horarios


def motivo_no_valido(
    agenda: Turno,
    momento: datetime,
    ahora: datetime,
    bloqueados: dict[date, str] | None = None,
) -> str | None:
    """Por qué ese momento no es un horario reservable de la agenda, o None."""
    local = momento.astimezone(ZONA_HORARIA)
    bloqueados = bloqueados or {}
    if local <= ahora:
        return "Ese horario ya pasó."
    if local.date() > ahora.date() + timedelta(days=agenda.anticipacion_maxima_dias):
        return (
            f"Los turnos de {agenda.nombre} se dan con hasta "
            f"{agenda.anticipacion_maxima_dias} días de anticipación."
        )
    if local.date() in bloqueados:
        return f"El {fecha_en_palabras(local.date())} no hay atención: {bloqueados[local.date()]}."
    if local.weekday() not in agenda.dias:
        dia = DIAS_SEMANA[local.weekday()]
        return f"{agenda.nombre} no atiende los {dia if dia.endswith('s') else dia + 's'}."
    if local not in horarios_del_dia(agenda, local.date()):
        return f"Los turnos de {agenda.nombre} son {horario_de_atencion(agenda)}."
    return None


async def dias_bloqueados(
    db: AsyncSession, agenda_id: uuid.UUID | None, desde: date, hasta: date
) -> dict[date, str]:
    """Los días sin atención del rango [desde, hasta), de esa agenda o de todas."""
    consulta = select(DiaBloqueado.fecha, DiaBloqueado.motivo).where(
        DiaBloqueado.fecha >= desde,
        DiaBloqueado.fecha < hasta,
        or_(DiaBloqueado.turno_id.is_(None), DiaBloqueado.turno_id == agenda_id),
    )
    return {fecha: motivo for fecha, motivo in (await db.execute(consulta)).all()}


async def ocupacion(
    db: AsyncSession, agenda_id: uuid.UUID, desde: datetime, hasta: datetime
) -> dict[datetime, int]:
    """Cuántas reservas confirmadas hay en cada horario del rango."""
    consulta = (
        select(Reserva.fecha_hora, func.count())
        .where(
            Reserva.turno_id == agenda_id,
            Reserva.estado == EstadoReserva.confirmada,
            Reserva.fecha_hora >= desde,
            Reserva.fecha_hora < hasta,
        )
        .group_by(Reserva.fecha_hora)
    )
    return {fecha_hora: cantidad for fecha_hora, cantidad in (await db.execute(consulta)).all()}


async def disponibilidad(
    db: AsyncSession, agenda: Turno, desde: date, dias: int, ahora: datetime | None = None
) -> list[dict]:
    """Cada horario de la grilla entre `desde` y `desde + dias`, con su ocupación."""
    ahora = ahora or ahora_local()
    inicio = datetime.combine(desde, time(0, 0), tzinfo=ZONA_HORARIA)
    ocupados = await ocupacion(db, agenda.id, inicio, inicio + timedelta(days=dias))
    bloqueados = await dias_bloqueados(db, agenda.id, desde, desde + timedelta(days=dias))
    limite = ahora.date() + timedelta(days=agenda.anticipacion_maxima_dias)
    horarios = []
    for desplazamiento in range(dias):
        dia = desde + timedelta(days=desplazamiento)
        for momento in horarios_del_dia(agenda, dia, bloqueados):
            horarios.append(
                {
                    "fecha_hora": momento,
                    "ocupados": ocupados.get(momento, 0),
                    "cupos": agenda.cupos_por_horario,
                    "reservable": momento > ahora and dia <= limite,
                }
            )
    return horarios


async def proximos_horarios_libres(
    db: AsyncSession,
    agenda: Turno,
    ahora: datetime | None = None,
    cantidad: int = ALTERNATIVAS,
) -> list[datetime]:
    """Los primeros horarios libres para ofrecer cuando el vecino pide un turno
    sin decir el día: el primero libre de cada día, en días distintos, para que
    tenga opciones reales para elegir y no tres horarios seguidos de la misma
    mañana. Si no alcanzan los días, se completa con los que siguen."""
    ahora = ahora or ahora_local()
    libres = [
        horario["fecha_hora"]
        for horario in await disponibilidad(db, agenda, ahora.date(), DIAS_DE_BUSQUEDA * 2, ahora)
        if horario["reservable"] and horario["ocupados"] < horario["cupos"]
    ]
    elegidos: list[datetime] = []
    dias_usados: set[date] = set()
    for momento in libres:
        if momento.astimezone(ZONA_HORARIA).date() not in dias_usados:
            elegidos.append(momento)
            dias_usados.add(momento.astimezone(ZONA_HORARIA).date())
        if len(elegidos) == cantidad:
            break
    for momento in libres:
        if len(elegidos) == cantidad:
            break
        if momento not in elegidos:
            elegidos.append(momento)
    return sorted(elegidos)


async def horarios_libres_cercanos(
    db: AsyncSession,
    agenda: Turno,
    pedido: datetime,
    ahora: datetime | None = None,
    cantidad: int = ALTERNATIVAS,
) -> list[datetime]:
    """Los horarios libres más cercanos al pedido, en orden cronológico."""
    ahora = ahora or ahora_local()
    desde = max(pedido.astimezone(ZONA_HORARIA).date(), ahora.date())
    libres = [
        horario["fecha_hora"]
        for horario in await disponibilidad(db, agenda, desde, DIAS_DE_BUSQUEDA, ahora)
        if horario["reservable"] and horario["ocupados"] < horario["cupos"]
    ]
    cercanos = sorted(libres, key=lambda momento: abs(momento - pedido))[:cantidad]
    return sorted(cercanos)


async def reservar(
    db: AsyncSession,
    *,
    agenda_id: uuid.UUID,
    ciudadano_id: uuid.UUID,
    caso_id: uuid.UUID,
    momento: datetime,
    ahora: datetime | None = None,
) -> Reserva:
    """Reserva el horario si se puede; si no, `ReservaNoDisponible`.

    La agenda se bloquea (`FOR UPDATE`) hasta el commit del caller: dos pedidos
    simultáneos por el último cupo de un horario se atienden de a uno, y el
    segundo ya ve la reserva del primero. No hace commit.
    """
    ahora = ahora or ahora_local()
    agenda = (
        await db.execute(select(Turno).where(Turno.id == agenda_id).with_for_update())
    ).scalar_one()

    await _validar_horario(db, agenda, momento, ahora)

    # Un turno pendiente por trámite, como en cualquier turnero: para cambiarlo,
    # primero se cancela el que tiene.
    vigente = (
        await db.execute(
            select(Reserva).where(
                Reserva.ciudadano_id == ciudadano_id,
                Reserva.turno_id == agenda.id,
                Reserva.estado == EstadoReserva.confirmada,
                Reserva.fecha_hora > ahora,
            )
        )
    ).scalars().first()
    if vigente is not None:
        raise ReservaNoDisponible(
            f"Ya tiene un turno de {agenda.nombre} para el {momento_en_palabras(vigente.fecha_hora)}.",
            vigente=vigente,
        )

    choque = (
        await db.execute(
            select(Reserva.id).where(
                Reserva.ciudadano_id == ciudadano_id,
                Reserva.estado == EstadoReserva.confirmada,
                Reserva.fecha_hora == momento,
            )
        )
    ).first()
    if choque is not None:
        raise ReservaNoDisponible(
            "Ya tiene otro turno en ese mismo horario.",
            alternativas=await horarios_libres_cercanos(db, agenda, momento, ahora),
        )

    ocupados = (await ocupacion(db, agenda.id, momento, momento + timedelta(seconds=1))).get(momento, 0)
    if ocupados >= agenda.cupos_por_horario:
        raise ReservaNoDisponible(
            "Ese horario ya está completo.",
            alternativas=await horarios_libres_cercanos(db, agenda, momento, ahora),
        )

    reserva = Reserva(
        turno_id=agenda.id, caso_id=caso_id, ciudadano_id=ciudadano_id, fecha_hora=momento
    )
    try:
        # El índice único por ciudadano y horario es la red de seguridad para
        # el choque entre dos agendas distintas, que el bloqueo no cubre.
        async with db.begin_nested():
            db.add(reserva)
            await db.flush()
    except IntegrityError as error:
        raise ReservaNoDisponible("Ya tiene otro turno en ese mismo horario.") from error
    return reserva


async def _validar_horario(db: AsyncSession, agenda: Turno, momento: datetime, ahora: datetime) -> None:
    dia = momento.astimezone(ZONA_HORARIA).date()
    bloqueados = await dias_bloqueados(db, agenda.id, dia, dia + timedelta(days=1))
    motivo = motivo_no_valido(agenda, momento, ahora, bloqueados)
    if motivo is not None:
        raise ReservaNoDisponible(
            motivo, alternativas=await horarios_libres_cercanos(db, agenda, momento, ahora)
        )


async def reprogramar_reserva(
    db: AsyncSession,
    reserva: Reserva,
    momento: datetime,
    *,
    actor: str,
    actor_tipo: ActorInteraccion,
    ahora: datetime | None = None,
) -> datetime:
    """Mueve el turno a otro horario de la misma agenda, con las mismas reglas
    que una reserva nueva. Devuelve el horario anterior. No hace commit.

    Se mueve la misma reserva, no se cancela y se crea otra: el número de caso
    que tiene el ciudadano sigue valiendo, y el horario viejo queda libre en el
    mismo paso.
    """
    ahora = ahora or ahora_local()
    if reserva.estado != EstadoReserva.confirmada:
        raise ValueError("Solo se puede cambiar un turno confirmado.")
    agenda = (
        await db.execute(select(Turno).where(Turno.id == reserva.turno_id).with_for_update())
    ).scalar_one()
    await _validar_horario(db, agenda, momento, ahora)

    anterior = reserva.fecha_hora
    if momento == anterior:
        return anterior
    choque = (
        await db.execute(
            select(Reserva.id).where(
                Reserva.ciudadano_id == reserva.ciudadano_id,
                Reserva.estado == EstadoReserva.confirmada,
                Reserva.fecha_hora == momento,
                Reserva.id != reserva.id,
            )
        )
    ).first()
    if choque is not None:
        raise ReservaNoDisponible(
            "Ya tiene otro turno en ese mismo horario.",
            alternativas=await horarios_libres_cercanos(db, agenda, momento, ahora),
        )
    ocupados = (await ocupacion(db, agenda.id, momento, momento + timedelta(seconds=1))).get(momento, 0)
    if ocupados >= agenda.cupos_por_horario:
        raise ReservaNoDisponible(
            "Ese horario ya está completo.",
            alternativas=await horarios_libres_cercanos(db, agenda, momento, ahora),
        )

    reserva.fecha_hora = momento
    # El recordatorio era del horario anterior: el nuevo se recuerda de nuevo.
    reserva.recordatorio_enviado_en = None
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as error:
        raise ReservaNoDisponible("Ya tiene otro turno en ese mismo horario.") from error
    await registrar_auditoria(
        db,
        caso_id=reserva.caso_id,
        accion="reprogramacion_reserva",
        actor=actor,
        actor_tipo=actor_tipo,
        metadata={
            "anterior": anterior.astimezone(ZONA_HORARIA).isoformat(),
            "nueva": momento.astimezone(ZONA_HORARIA).isoformat(),
        },
    )
    return anterior


async def cancelar_reserva(
    db: AsyncSession,
    reserva: Reserva,
    *,
    actor: str,
    actor_tipo: ActorInteraccion,
    motivo: str | None = None,
) -> Reserva:
    """Cancela un turno confirmado y libera su cupo. No hace commit."""
    if reserva.estado != EstadoReserva.confirmada:
        raise ValueError("Solo se puede cancelar un turno confirmado.")
    reserva.estado = EstadoReserva.cancelada
    reserva.cancelada_en = ahora_local()
    reserva.motivo_cancelacion = motivo
    await registrar_auditoria(
        db,
        caso_id=reserva.caso_id,
        accion="cancelacion_reserva",
        actor=actor,
        actor_tipo=actor_tipo,
        metadata={
            "fecha_hora": reserva.fecha_hora.astimezone(ZONA_HORARIA).isoformat(),
            **({"motivo": motivo} if motivo else {}),
        },
    )
    return reserva


async def registrar_asistencia(
    db: AsyncSession, reserva: Reserva, estado: EstadoReserva, *, actor: str
) -> Reserva:
    """Marca el turno como atendido o ausente. No hace commit."""
    if estado not in (EstadoReserva.atendida, EstadoReserva.ausente):
        raise ValueError("La asistencia es atendida o ausente.")
    if reserva.estado == EstadoReserva.cancelada:
        raise ValueError("El turno está cancelado.")
    reserva.estado = estado
    await registrar_auditoria(
        db,
        caso_id=reserva.caso_id,
        accion=f"turno_{estado.value}",
        actor=actor,
        actor_tipo=ActorInteraccion.operador,
    )
    return reserva


async def reservas_vigentes_del_ciudadano(
    db: AsyncSession, ciudadano_id: uuid.UUID, ahora: datetime | None = None
) -> list[Reserva]:
    """Sus turnos confirmados que todavía no pasaron, del más próximo al más lejano."""
    ahora = ahora or ahora_local()
    consulta = (
        select(Reserva)
        .options(selectinload(Reserva.turno), selectinload(Reserva.caso))
        .where(
            Reserva.ciudadano_id == ciudadano_id,
            Reserva.estado == EstadoReserva.confirmada,
            Reserva.fecha_hora > ahora,
        )
        .order_by(Reserva.fecha_hora)
    )
    return list((await db.execute(consulta)).scalars().all())


async def obtener_reserva(db: AsyncSession, reserva_id: uuid.UUID) -> Reserva | None:
    consulta = (
        select(Reserva)
        .options(
            selectinload(Reserva.turno),
            selectinload(Reserva.ciudadano),
            selectinload(Reserva.caso),
        )
        .where(Reserva.id == reserva_id)
    )
    return (await db.execute(consulta)).scalars().first()


async def listar_turnos_con_reservas(
    db: AsyncSession, desde: datetime | None = None, hasta: datetime | None = None
) -> list[Turno]:
    """Las agendas con sus reservas; con rango, solo las de ese rango."""
    relacion = Turno.reservas
    if desde is not None and hasta is not None:
        relacion = Turno.reservas.and_(Reserva.fecha_hora >= desde, Reserva.fecha_hora < hasta)
    cargar = selectinload(relacion)
    consulta = (
        select(Turno)
        .options(
            cargar.selectinload(Reserva.ciudadano),
            cargar.selectinload(Reserva.caso),
        )
        .order_by(Turno.nombre)
    )
    return list((await db.execute(consulta)).scalars().all())


async def obtener_turno(db: AsyncSession, turno_id: uuid.UUID) -> Turno | None:
    return await db.get(Turno, turno_id)


async def obtener_turno_por_nombre(db: AsyncSession, nombre: str) -> Turno | None:
    """Búsqueda tolerante: el LLM manda el nombre del turno como texto."""
    consulta = select(Turno).where(Turno.nombre.ilike(f"%{nombre.strip()}%")).limit(2)
    coincidencias = list((await db.execute(consulta)).scalars().all())
    # Con más de una coincidencia no hay forma segura de elegir.
    return coincidencias[0] if len(coincidencias) == 1 else None


async def listar_nombres_de_turnos(db: AsyncSession) -> list[str]:
    consulta = select(Turno.nombre).order_by(Turno.nombre)
    return list((await db.execute(consulta)).scalars().all())


async def listar_agendas(db: AsyncSession) -> list[Turno]:
    return list((await db.execute(select(Turno).order_by(Turno.nombre))).scalars().all())


async def listar_bloqueos(db: AsyncSession, desde: date) -> list[DiaBloqueado]:
    consulta = select(DiaBloqueado).where(DiaBloqueado.fecha >= desde).order_by(DiaBloqueado.fecha)
    return list((await db.execute(consulta)).scalars().all())


async def turnos_del_dia(
    db: AsyncSession, dia: date, agenda_id: uuid.UUID | None = None
) -> list[Reserva]:
    """Los turnos confirmados de ese día, de una agenda o de todas."""
    inicio = datetime.combine(dia, time(0, 0), tzinfo=ZONA_HORARIA)
    consulta = (
        select(Reserva)
        .options(selectinload(Reserva.turno), selectinload(Reserva.ciudadano), selectinload(Reserva.caso))
        .where(
            Reserva.estado == EstadoReserva.confirmada,
            Reserva.fecha_hora >= inicio,
            Reserva.fecha_hora < inicio + timedelta(days=1),
        )
        .order_by(Reserva.fecha_hora)
    )
    if agenda_id is not None:
        consulta = consulta.where(Reserva.turno_id == agenda_id)
    return list((await db.execute(consulta)).scalars().all())


async def bloquear_dia(
    db: AsyncSession, *, fecha: date, motivo: str, agenda_id: uuid.UUID | None = None
) -> tuple[DiaBloqueado, list[Reserva]]:
    """Bloquea el día y devuelve los turnos confirmados que ya había ese día,
    para que el organismo decida qué hacer con ellos. No los cancela solo: avisar
    a cada vecino es una decisión del organismo. No hace commit."""
    bloqueo = DiaBloqueado(turno_id=agenda_id, fecha=fecha, motivo=motivo)
    db.add(bloqueo)
    await db.flush()
    return bloqueo, await turnos_del_dia(db, fecha, agenda_id)


async def reservas_para_recordar(db: AsyncSession, dia: date) -> list[Reserva]:
    """Los turnos confirmados de ese día a los que todavía no se les mandó el
    recordatorio."""
    return [r for r in await turnos_del_dia(db, dia) if r.recordatorio_enviado_en is None]
