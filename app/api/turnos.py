import uuid
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.recordatorios import enviar_recordatorios
from app.core.dependencies import get_current_user, requiere_rol
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.ciudadanos import obtener_ciudadano_por_documento
from app.db.crud.interacciones import crear_interaccion
from app.db.crud.turnos import (
    ZONA_HORARIA,
    ReservaNoDisponible,
    bloquear_dia,
    cancelar_reserva,
    dias_bloqueados,
    disponibilidad,
    horario_de_atencion,
    horarios_del_dia,
    listar_bloqueos,
    listar_turnos_con_reservas,
    obtener_reserva,
    obtener_turno,
    registrar_asistencia,
    reprogramar_reserva,
    reservar,
)
from app.db.models import (
    ActorInteraccion,
    Canal,
    Caso,
    Ciudadano,
    DiaBloqueado,
    EstadoCaso,
    EstadoReserva,
    Reserva,
    RolUsuario,
    TipoCaso,
    Turno,
    Usuario,
)
from app.db.session import get_db
from app.schemas.turno import (
    AgendaUpdate,
    AsistenciaIn,
    BloqueoCreado,
    BloqueoIn,
    BloqueoOut,
    CancelacionIn,
    HorarioOut,
    RecordatoriosIn,
    RecordatoriosOut,
    ReprogramacionIn,
    ReservaOut,
    ReservaPanelIn,
    TurnoOut,
)

router = APIRouter(prefix="/api/turnos", tags=["turnos"])
solo_supervisor = requiere_rol(RolUsuario.supervisor)

# Una semana es lo que muestra el panel; el tope evita pedir meses de grilla.
DIAS_POR_DEFECTO = 7
DIAS_MAXIMOS = 31


def _reserva_out(reserva: Reserva) -> ReservaOut:
    return ReservaOut(
        id=reserva.id,
        caso_id=reserva.caso_id,
        referencia=reserva.caso.referencia,
        ciudadano=reserva.ciudadano,
        fecha_hora=reserva.fecha_hora,
        estado=reserva.estado.value,
        motivo_cancelacion=reserva.motivo_cancelacion,
        cancelada_en=reserva.cancelada_en,
        recordatorio_enviado_en=reserva.recordatorio_enviado_en,
        created_at=reserva.created_at,
    )


def _turno_out(turno: Turno, desde: date, dias: int, bloqueos: list[DiaBloqueado]) -> TurnoOut:
    propios = [b for b in bloqueos if b.turno_id in (None, turno.id)]
    bloqueados = {b.fecha: b.motivo for b in propios}
    horarios = sum(
        len(horarios_del_dia(turno, desde + timedelta(days=d), bloqueados)) for d in range(dias)
    )
    reservas = sorted(turno.reservas, key=lambda r: r.fecha_hora)
    return TurnoOut(
        id=turno.id,
        nombre=turno.nombre,
        descripcion=turno.descripcion,
        sede=turno.sede,
        dias_atencion=turno.dias,
        hora_apertura=turno.hora_apertura.strftime("%H:%M"),
        hora_cierre=turno.hora_cierre.strftime("%H:%M"),
        duracion_minutos=turno.duracion_minutos,
        cupos_por_horario=turno.cupos_por_horario,
        anticipacion_maxima_dias=turno.anticipacion_maxima_dias,
        horario=horario_de_atencion(turno),
        capacidad=horarios * turno.cupos_por_horario,
        ocupados=sum(1 for r in reservas if r.estado == EstadoReserva.confirmada),
        reservas=[_reserva_out(r) for r in reservas],
        bloqueos=[BloqueoOut.model_validate(b) for b in propios],
    )


def _rango(desde: date | None, dias: int) -> tuple[date, datetime, datetime]:
    desde = desde or datetime.now(ZONA_HORARIA).date()
    inicio = datetime.combine(desde, time(0, 0), tzinfo=ZONA_HORARIA)
    return desde, inicio, inicio + timedelta(days=dias)


@router.get("", response_model=list[TurnoOut])
async def listar(
    desde: date | None = None,
    dias: int = Query(DIAS_POR_DEFECTO, ge=1, le=DIAS_MAXIMOS),
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[TurnoOut]:
    """Las agendas con su grilla y las reservas del rango (por defecto, desde hoy
    y una semana), en cualquier estado."""
    desde, inicio, fin = _rango(desde, dias)
    turnos = await listar_turnos_con_reservas(db, inicio, fin)
    bloqueos = [b for b in await listar_bloqueos(db, desde) if b.fecha < desde + timedelta(days=dias)]
    return [_turno_out(turno, desde, dias, bloqueos) for turno in turnos]


@router.get("/{turno_id}/disponibilidad", response_model=list[HorarioOut])
async def ver_disponibilidad(
    turno_id: uuid.UUID,
    desde: date | None = None,
    dias: int = Query(DIAS_POR_DEFECTO, ge=1, le=DIAS_MAXIMOS),
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[HorarioOut]:
    turno = await obtener_turno(db, turno_id)
    if turno is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda no encontrada")
    desde, _, _ = _rango(desde, dias)
    return [HorarioOut(**horario) for horario in await disponibilidad(db, turno, desde, dias)]


async def _reserva_o_404(db: AsyncSession, reserva_id: uuid.UUID) -> Reserva:
    reserva = await obtener_reserva(db, reserva_id)
    if reserva is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no encontrada")
    return reserva


@router.post("/reservas/{reserva_id}/cancelar", response_model=ReservaOut)
async def cancelar(
    reserva_id: uuid.UUID,
    datos: CancelacionIn,
    db: AsyncSession = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> ReservaOut:
    """Cancela el turno y libera el horario para otra persona."""
    reserva = await _reserva_o_404(db, reserva_id)
    try:
        await cancelar_reserva(
            db,
            reserva,
            actor=usuario.email,
            actor_tipo=ActorInteraccion.operador,
            motivo=datos.motivo,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    salida = _reserva_out(reserva)
    await db.commit()
    return salida


@router.post("/reservas/{reserva_id}/asistencia", response_model=ReservaOut)
async def asistencia(
    reserva_id: uuid.UUID,
    datos: AsistenciaIn,
    db: AsyncSession = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> ReservaOut:
    """Registra si el ciudadano vino (atendida) o no (ausente)."""
    reserva = await _reserva_o_404(db, reserva_id)
    try:
        await registrar_asistencia(db, reserva, EstadoReserva(datos.estado), actor=usuario.email)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    salida = _reserva_out(reserva)
    await db.commit()
    return salida


def _no_disponible(error: ReservaNoDisponible) -> HTTPException:
    """409 con el motivo y los horarios libres más cercanos, para que el panel
    los ofrezca."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "motivo": error.motivo,
            "alternativas": [m.astimezone(ZONA_HORARIA).isoformat() for m in error.alternativas],
        },
    )


def _en_argentina(momento: datetime) -> datetime:
    """El panel manda la hora del turno sin zona: es la del organismo."""
    return momento.replace(tzinfo=ZONA_HORARIA) if momento.tzinfo is None else momento


@router.post("/{turno_id}/reservas", response_model=ReservaOut, status_code=status.HTTP_201_CREATED)
async def reservar_desde_el_panel(
    turno_id: uuid.UUID,
    datos: ReservaPanelIn,
    db: AsyncSession = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> ReservaOut:
    """Turno cargado por el operador para quien llamó o se acercó a la sede, con
    las mismas reglas que una reserva del agente."""
    if await obtener_turno(db, turno_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda no encontrada")
    ciudadano = await obtener_ciudadano_por_documento(db, datos.documento)
    if ciudadano is None:
        if not datos.nombre or not datos.nombre.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El DNI no está registrado: hace falta el nombre del ciudadano",
            )
        ciudadano = Ciudadano(documento=datos.documento, nombre=datos.nombre.strip())
        db.add(ciudadano)
        await db.flush()

    try:
        async with db.begin_nested():
            caso = Caso(
                ciudadano_id=ciudadano.id,
                tipo=TipoCaso.reserva,
                # El pedido queda resuelto con el turno dado.
                estado=EstadoCaso.cerrado,
                motivo_cierre="resuelto",
                canal_origen=Canal(datos.canal),
                canal_actual=Canal(datos.canal),
            )
            db.add(caso)
            await db.flush()
            reserva = await reservar(
                db,
                agenda_id=turno_id,
                ciudadano_id=ciudadano.id,
                caso_id=caso.id,
                momento=_en_argentina(datos.fecha_hora),
            )
    except ReservaNoDisponible as error:
        raise _no_disponible(error) from error

    await crear_interaccion(
        db,
        caso_id=caso.id,
        contenido=f"Turno cargado desde el panel por {usuario.email}.",
        canal=Canal(datos.canal),
        actor=ActorInteraccion.operador,
        interna=True,
    )
    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="creacion_reserva",
        actor=usuario.email,
        actor_tipo=ActorInteraccion.operador,
        metadata={"fecha_hora": reserva.fecha_hora.astimezone(ZONA_HORARIA).isoformat()},
    )
    await db.commit()
    return _reserva_out(await _reserva_o_404(db, reserva.id))


@router.post("/reservas/{reserva_id}/reprogramar", response_model=ReservaOut)
async def reprogramar(
    reserva_id: uuid.UUID,
    datos: ReprogramacionIn,
    db: AsyncSession = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> ReservaOut:
    """Mueve el turno a otro horario de la misma agenda y libera el anterior."""
    reserva = await _reserva_o_404(db, reserva_id)
    try:
        await reprogramar_reserva(
            db,
            reserva,
            _en_argentina(datos.fecha_hora),
            actor=usuario.email,
            actor_tipo=ActorInteraccion.operador,
        )
    except ReservaNoDisponible as error:
        raise _no_disponible(error) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await db.commit()
    return _reserva_out(await _reserva_o_404(db, reserva_id))


@router.patch("/{turno_id}", response_model=TurnoOut)
async def configurar_agenda(
    turno_id: uuid.UUID,
    datos: AgendaUpdate,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> TurnoOut:
    """Ajusta la grilla de la agenda. Los turnos ya dados no se tocan."""
    turno = await obtener_turno(db, turno_id)
    if turno is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda no encontrada")
    cambios = datos.model_dump(exclude_unset=True)
    apertura = cambios.get("hora_apertura", turno.hora_apertura)
    cierre = cambios.get("hora_cierre", turno.hora_cierre)
    if apertura >= cierre:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La hora de apertura tiene que ser anterior a la de cierre",
        )
    if "dias_atencion" in cambios:
        cambios["dias_atencion"] = ",".join(str(d) for d in sorted(set(cambios["dias_atencion"])))
    for campo, valor in cambios.items():
        setattr(turno, campo, valor)
    await db.commit()
    desde, inicio, fin = _rango(None, 7)
    turnos = await listar_turnos_con_reservas(db, inicio, fin)
    bloqueos = [b for b in await listar_bloqueos(db, desde) if b.fecha < desde + timedelta(days=7)]
    return next(_turno_out(t, desde, 7, bloqueos) for t in turnos if t.id == turno_id)


@router.get("/bloqueos/proximos", response_model=list[BloqueoOut])
async def proximos_bloqueos(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[BloqueoOut]:
    hoy = datetime.now(ZONA_HORARIA).date()
    return [BloqueoOut.model_validate(b) for b in await listar_bloqueos(db, hoy)]


@router.post("/bloqueos", response_model=BloqueoCreado, status_code=status.HTTP_201_CREATED)
async def bloquear(
    datos: BloqueoIn,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> BloqueoCreado:
    """Bloquea un día (feriado o jornada sin atención) y devuelve los turnos que
    ya había ese día, para que el supervisor decida si los cancela."""
    if datos.turno_id is not None and await obtener_turno(db, datos.turno_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda no encontrada")
    existentes = await dias_bloqueados(db, datos.turno_id, datos.fecha, datos.fecha + timedelta(days=1))
    if existentes:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese día ya está bloqueado")
    bloqueo, afectados = await bloquear_dia(
        db, fecha=datos.fecha, motivo=datos.motivo.strip(), agenda_id=datos.turno_id
    )
    salida = BloqueoCreado(
        bloqueo=BloqueoOut.model_validate(bloqueo), afectados=[_reserva_out(r) for r in afectados]
    )
    await db.commit()
    return salida


@router.delete("/bloqueos/{bloqueo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def desbloquear(
    bloqueo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> None:
    bloqueo = await db.get(DiaBloqueado, bloqueo_id)
    if bloqueo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloqueo no encontrado")
    await db.delete(bloqueo)
    await db.commit()


@router.post("/recordatorios", response_model=RecordatoriosOut)
async def recordatorios(
    datos: RecordatoriosIn,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> RecordatoriosOut:
    """Manda ahora los recordatorios de los turnos de mañana (o del día pedido)."""
    return RecordatoriosOut(**await enviar_recordatorios(db, datos.fecha))
