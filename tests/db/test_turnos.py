"""Reglas de la agenda de turnos: la grilla, los cupos y la cancelación."""

import asyncio
from datetime import time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.crud.turnos import (
    ReservaNoDisponible,
    ahora_local,
    cancelar_reserva,
    disponibilidad,
    horario_de_atencion,
    horarios_del_dia,
    horarios_libres_cercanos,
    registrar_asistencia,
    reservar,
)
from app.db.models import ActorInteraccion, Canal, Caso, Ciudadano, EstadoReserva, TipoCaso, Turno
from tests.horarios import dia_habil, momento


@pytest.fixture
async def agenda(db_session) -> Turno:
    turno = Turno(
        nombre="Renovación de DNI",
        descripcion="Centro de documentación.",
        dias_atencion="0,1,2,3,4",
        hora_apertura=time(8, 0),
        hora_cierre=time(12, 0),
        duracion_minutos=30,
        cupos_por_horario=1,
        anticipacion_maxima_dias=30,
    )
    db_session.add(turno)
    await db_session.commit()
    return turno


async def _vecino(db_session, documento: str) -> tuple[Ciudadano, Caso]:
    persona = Ciudadano(documento=documento, nombre=f"Vecino {documento}", telefono=f"+54911{documento}")
    db_session.add(persona)
    await db_session.flush()
    caso = Caso(
        ciudadano_id=persona.id, tipo=TipoCaso.reserva, canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp
    )
    db_session.add(caso)
    await db_session.commit()
    return persona, caso


async def _reservar(db_session, agenda, persona, caso, cuando):
    reserva = await reservar(
        db_session, agenda_id=agenda.id, ciudadano_id=persona.id, caso_id=caso.id, momento=cuando
    )
    await db_session.commit()
    return reserva


# --- La grilla ---------------------------------------------------------------


def test_la_grilla_va_de_la_apertura_al_cierre_cada_duracion(agenda):
    horarios = horarios_del_dia(agenda, dia_habil())
    assert [h.strftime("%H:%M") for h in horarios] == [
        "08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    ]


def test_un_dia_que_la_agenda_no_atiende_no_tiene_horarios(agenda):
    sabado = dia_habil()
    while sabado.weekday() != 5:
        sabado += timedelta(days=1)
    assert horarios_del_dia(agenda, sabado) == []


def test_el_horario_de_atencion_se_lee_en_castellano(agenda):
    assert horario_de_atencion(agenda) == "de lunes a viernes de 8:00 a 12:00, cada 30 minutos"


# --- Validaciones al reservar ------------------------------------------------


async def test_no_se_puede_reservar_dos_veces_el_mismo_horario(db_session, agenda):
    ana, caso_ana = await _vecino(db_session, "20111111")
    beto, caso_beto = await _vecino(db_session, "20222222")
    await _reservar(db_session, agenda, ana, caso_ana, momento(hora="10:00"))

    with pytest.raises(ReservaNoDisponible, match="completo") as error:
        await _reservar(db_session, agenda, beto, caso_beto, momento(hora="10:00"))

    # Le ofrece los libres más cercanos, y el ocupado no está entre ellos.
    alternativas = [m.strftime("%H:%M") for m in error.value.alternativas]
    assert len(alternativas) == 3
    assert "10:00" not in alternativas
    assert "09:30" in alternativas and "10:30" in alternativas


async def test_con_dos_cupos_entran_dos_y_no_un_tercero(db_session, agenda):
    agenda.cupos_por_horario = 2
    await db_session.commit()
    personas = [await _vecino(db_session, documento) for documento in ("20111111", "20222222", "20333333")]

    await _reservar(db_session, agenda, *personas[0], momento(hora="9:00"))
    await _reservar(db_session, agenda, *personas[1], momento(hora="9:00"))
    with pytest.raises(ReservaNoDisponible, match="completo"):
        await _reservar(db_session, agenda, *personas[2], momento(hora="9:00"))


async def test_cancelar_libera_el_horario(db_session, agenda):
    ana, caso_ana = await _vecino(db_session, "20111111")
    beto, caso_beto = await _vecino(db_session, "20222222")
    reserva = await _reservar(db_session, agenda, ana, caso_ana, momento(hora="10:00"))

    await cancelar_reserva(db_session, reserva, actor="agente", actor_tipo=ActorInteraccion.agente_ia)
    await db_session.commit()

    otra = await _reservar(db_session, agenda, beto, caso_beto, momento(hora="10:00"))
    assert otra.estado == EstadoReserva.confirmada
    assert reserva.estado == EstadoReserva.cancelada
    assert reserva.cancelada_en is not None


async def test_un_turno_cancelado_no_se_vuelve_a_cancelar(db_session, agenda):
    ana, caso = await _vecino(db_session, "20111111")
    reserva = await _reservar(db_session, agenda, ana, caso, momento())
    await cancelar_reserva(db_session, reserva, actor="agente", actor_tipo=ActorInteraccion.agente_ia)

    with pytest.raises(ValueError, match="confirmado"):
        await cancelar_reserva(db_session, reserva, actor="agente", actor_tipo=ActorInteraccion.agente_ia)


@pytest.mark.parametrize(
    ("cuando", "motivo"),
    [
        (lambda: momento(hora="10:15"), "cada 30 minutos"),
        (lambda: momento(hora="12:00"), "de 8:00 a 12:00"),
        (lambda: momento(hora="7:30"), "de 8:00 a 12:00"),
        (lambda: momento(desde_hoy=-7), "ya pasó"),
        (lambda: momento(desde_hoy=45), "30 días de anticipación"),
    ],
)
async def test_horarios_que_no_son_de_la_grilla(db_session, agenda, cuando, motivo):
    ana, caso = await _vecino(db_session, "20111111")
    with pytest.raises(ReservaNoDisponible, match=motivo):
        await _reservar(db_session, agenda, ana, caso, cuando())


async def test_un_fin_de_semana_no_se_reserva(db_session, agenda):
    ana, caso = await _vecino(db_session, "20111111")
    sabado = momento()
    while sabado.weekday() != 5:
        sabado += timedelta(days=1)
    with pytest.raises(ReservaNoDisponible, match="no atiende los sábados"):
        await _reservar(db_session, agenda, ana, caso, sabado)


async def test_un_turno_pendiente_por_tramite(db_session, agenda):
    """Para cambiarlo, primero se cancela el que tiene: como en cualquier turnero."""
    ana, caso = await _vecino(db_session, "20111111")
    primera = await _reservar(db_session, agenda, ana, caso, momento(hora="9:00"))

    with pytest.raises(ReservaNoDisponible, match="Ya tiene un turno") as error:
        await _reservar(db_session, agenda, ana, caso, momento(desde_hoy=5, hora="9:00"))
    assert error.value.vigente.id == primera.id


async def test_no_dos_turnos_a_la_misma_hora_aunque_sean_de_agendas_distintas(db_session, agenda):
    licencia = Turno(nombre="Licencia de conducir", descripcion="Sede comunal.", hora_cierre=time(12, 0))
    db_session.add(licencia)
    await db_session.commit()
    ana, caso = await _vecino(db_session, "20111111")
    await _reservar(db_session, agenda, ana, caso, momento(hora="10:00"))

    with pytest.raises(ReservaNoDisponible, match="mismo horario"):
        await _reservar(db_session, licencia, ana, caso, momento(hora="10:00"))


async def test_dos_pedidos_simultaneos_por_el_ultimo_cupo(db_engine, agenda, db_session):
    """El bloqueo de la agenda hace que se atiendan de a uno: entra uno solo."""
    ana, caso_ana = await _vecino(db_session, "20111111")
    beto, caso_beto = await _vecino(db_session, "20222222")
    sesiones = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def intentar(persona, caso):
        async with sesiones() as sesion:
            try:
                await reservar(
                    sesion, agenda_id=agenda.id, ciudadano_id=persona.id, caso_id=caso.id,
                    momento=momento(hora="11:00"),
                )
                await asyncio.sleep(0.2)  # mantiene el bloqueo mientras llega el otro
                await sesion.commit()
                return "reservó"
            except ReservaNoDisponible:
                await sesion.rollback()
                return "completo"

    resultados = await asyncio.gather(intentar(ana, caso_ana), intentar(beto, caso_beto))

    assert sorted(resultados) == ["completo", "reservó"]


# --- Disponibilidad y asistencia ----------------------------------------------


async def test_la_disponibilidad_cuenta_solo_las_confirmadas(db_session, agenda):
    ana, caso = await _vecino(db_session, "20111111")
    reserva = await _reservar(db_session, agenda, ana, caso, momento(hora="8:00"))
    await cancelar_reserva(db_session, reserva, actor="agente", actor_tipo=ActorInteraccion.agente_ia)
    beto, caso_beto = await _vecino(db_session, "20222222")
    await _reservar(db_session, agenda, beto, caso_beto, momento(hora="8:30"))

    horarios = {
        h["fecha_hora"].strftime("%H:%M"): h["ocupados"]
        for h in await disponibilidad(db_session, agenda, dia_habil(), 1)
    }
    assert horarios["08:00"] == 0
    assert horarios["08:30"] == 1


async def test_las_alternativas_no_incluyen_horarios_pasados(db_session, agenda):
    ahora = ahora_local()
    libres = await horarios_libres_cercanos(db_session, agenda, ahora - timedelta(days=3))
    assert libres and all(libre > ahora for libre in libres)


async def test_registrar_asistencia(db_session, agenda):
    ana, caso = await _vecino(db_session, "20111111")
    reserva = await _reservar(db_session, agenda, ana, caso, momento())

    await registrar_asistencia(db_session, reserva, EstadoReserva.ausente, actor="operador@test.com")
    assert reserva.estado == EstadoReserva.ausente

    with pytest.raises(ValueError):
        await registrar_asistencia(db_session, reserva, EstadoReserva.cancelada, actor="operador@test.com")


def test_hoy_mas_temprano_tambien_es_pasado(agenda):
    """No alcanza con mirar la fecha: un horario de hoy que ya pasó no se reserva."""
    from datetime import datetime

    from app.db.crud.turnos import ZONA_HORARIA, motivo_no_valido

    ahora = datetime.combine(dia_habil(), time(10, 15), tzinfo=ZONA_HORARIA)
    assert motivo_no_valido(agenda, ahora.replace(hour=10, minute=0), ahora) == "Ese horario ya pasó."
    assert motivo_no_valido(agenda, ahora.replace(hour=10, minute=30), ahora) is None


# --- Ofrecer horarios cuando el vecino no dijo el día --------------------------


async def test_ofrece_horarios_libres_en_dias_distintos_y_salta_los_tomados(db_session, agenda):
    from app.db.crud.turnos import proximos_horarios_libres

    ahora = momento(1, "07:00")
    primero = momento(1, "08:00")
    persona, caso = await _vecino(db_session, "40111222")
    await _reservar(db_session, agenda, persona, caso, primero)

    libres = await proximos_horarios_libres(db_session, agenda, ahora)

    assert len(libres) == 3
    assert primero not in libres, "un horario sin cupo no se ofrece"
    assert len({libre.date() for libre in libres}) == 3, "tres días distintos para elegir"


def test_el_pedido_de_dia_ofrece_los_horarios_libres():
    from app.agents.confirmacion import pedido_de_dia_y_hora

    agenda = Turno(nombre="Renovación de DNI")
    libres = [momento(2, "8:00"), momento(3, "9:30")]

    texto = pedido_de_dia_y_hora(agenda, Canal.whatsapp, libres)
    hablado = pedido_de_dia_y_hora(agenda, Canal.voz, libres)

    assert "próximos horarios libres de Renovación de DNI" in texto
    assert texto.count("\n- ") == 2
    assert hablado.startswith("Para Renovación de DNI tengo libre el ")
    assert "\n" not in hablado
