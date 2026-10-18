import uuid

import pytest
from langchain_core.tools import ToolException
from sqlalchemy import select

from app.db.models import Auditoria, Canal, Caso, Reserva, TipoCaso, Turno
from app.tools.reservas import crear_reserva


@pytest.fixture
async def turno_licencia(db_session) -> Turno:
    turno = Turno(
        nombre="Renovación de licencia de conducir",
        descripcion="Turnos en la sede comunal.",
    )
    db_session.add(turno)
    await db_session.commit()
    await db_session.refresh(turno)
    return turno


async def test_crear_reserva_registra_caso_reserva_y_auditoria(
    db_session, ciudadano, turno_licencia
):
    resultado = await crear_reserva(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.email,
        turno="renovación de licencia",
        fecha_hora="2026-08-15 10:00",
    )

    assert resultado["turno"] == turno_licencia.nombre
    assert resultado["fecha_hora"] == "2026-08-15 10:00"

    caso = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    assert caso is not None
    assert caso.tipo == TipoCaso.reserva

    reserva = await db_session.get(Reserva, uuid.UUID(resultado["reserva_id"]))
    assert reserva is not None
    assert reserva.turno_id == turno_licencia.id
    assert reserva.ciudadano_id == ciudadano.id

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert any(
        a.accion == "creacion_reserva" and a.metadata_["turno"] == turno_licencia.nombre
        for a in auditorias
    )


async def test_crear_reserva_con_turno_inexistente_lista_los_disponibles(
    db_session, ciudadano, turno_licencia
):
    with pytest.raises(ToolException, match="Renovación de licencia de conducir"):
        await crear_reserva(
            db_session,
            ciudadano_id=ciudadano.id,
            canal=Canal.email,
            turno="turno de pádel",
            fecha_hora="2026-08-15 10:00",
        )


async def test_crear_reserva_con_fecha_invalida_falla(db_session, ciudadano, turno_licencia):
    with pytest.raises(ToolException, match="AAAA-MM-DD HH:MM"):
        await crear_reserva(
            db_session,
            ciudadano_id=ciudadano.id,
            canal=Canal.email,
            turno="licencia",
            fecha_hora="el viernes a la tarde",
        )


async def test_crear_reserva_completa_el_caso_ya_abierto_en_vez_de_abrir_otro(
    db_session, ciudadano, turno_licencia
):
    """Mismo bug que en reclamos: el caso se abre al pedir el turno (todavía sin
    día ni horario) y, al confirmarlos, la tool creaba OTRO caso en vez de
    completar el que ya estaba abierto."""
    ya_abierto = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reserva,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(ya_abierto)
    await db_session.commit()

    resultado = await crear_reserva(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.whatsapp,
        turno="renovación de licencia",
        fecha_hora="2026-08-15 10:00",
        caso_id=ya_abierto.id,
    )

    assert resultado["caso_id"] == str(ya_abierto.id)

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1
