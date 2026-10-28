"""Pantalla de turnos: agendas con sus reservas."""

from datetime import datetime, timedelta, timezone

from app.db.models import Canal, Caso, Reserva, TipoCaso, Turno


async def test_listar_turnos_incluye_reservas_con_ciudadano(
    client, db_session, auth_headers, ciudadano
):
    turno = Turno(nombre="Renovación de DNI", descripcion="Centro de documentación.")
    vacio = Turno(nombre="Atención en CeSAC", descripcion="Atención primaria.")
    db_session.add_all([turno, vacio])
    await db_session.flush()

    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reserva,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Reserva(
            turno_id=turno.id,
            caso_id=caso.id,
            ciudadano_id=ciudadano.id,
            fecha_hora=datetime.now(timezone.utc) + timedelta(days=2),
        )
    )
    await db_session.commit()

    response = await client.get("/api/turnos", headers=auth_headers)

    assert response.status_code == 200
    agendas = {t["nombre"]: t for t in response.json()}
    assert agendas["Renovación de DNI"]["reservas"][0]["ciudadano"]["nombre"] == ciudadano.nombre
    assert agendas["Atención en CeSAC"]["reservas"] == []


async def test_listar_turnos_requiere_autenticacion(client):
    response = await client.get("/api/turnos")

    assert response.status_code == 401


async def _agenda_con_reserva(db_session, ciudadano):
    from datetime import time

    from app.db.crud.turnos import reservar
    from tests.horarios import momento

    agenda = Turno(nombre="Atención en CeSAC", descripcion="Atención primaria.", hora_cierre=time(12, 0))
    db_session.add(agenda)
    caso = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reserva, canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp
    )
    db_session.add(caso)
    await db_session.flush()
    reserva = await reservar(
        db_session, agenda_id=agenda.id, ciudadano_id=ciudadano.id, caso_id=caso.id, momento=momento(hora="9:00")
    )
    await db_session.commit()
    return agenda, reserva


async def test_la_agenda_trae_su_grilla_y_su_ocupacion(client, db_session, auth_headers, ciudadano):
    from tests.horarios import dia_habil

    agenda, _ = await _agenda_con_reserva(db_session, ciudadano)

    response = await client.get(
        "/api/turnos", params={"desde": dia_habil().isoformat(), "dias": 1}, headers=auth_headers
    )

    datos = {t["nombre"]: t for t in response.json()}["Atención en CeSAC"]
    assert datos["hora_apertura"] == "08:00" and datos["hora_cierre"] == "12:00"
    assert datos["capacidad"] == 8
    assert datos["ocupados"] == 1
    assert datos["reservas"][0]["estado"] == "confirmada"
    assert datos["reservas"][0]["referencia"].startswith("RES-")


async def test_disponibilidad_marca_el_horario_ocupado(client, db_session, auth_headers, ciudadano):
    from tests.horarios import dia_habil

    agenda, _ = await _agenda_con_reserva(db_session, ciudadano)

    response = await client.get(
        f"/api/turnos/{agenda.id}/disponibilidad",
        params={"desde": dia_habil().isoformat(), "dias": 1},
        headers=auth_headers,
    )

    ocupados = {h["fecha_hora"][11:16]: h["ocupados"] for h in response.json()}
    assert ocupados["09:00"] == 1
    assert ocupados["09:30"] == 0


async def test_el_operador_cancela_un_turno_y_queda_auditado(
    client, db_session, headers_operador, ciudadano
):
    from sqlalchemy import select

    from app.db.models import Auditoria

    _, reserva = await _agenda_con_reserva(db_session, ciudadano)

    response = await client.post(
        f"/api/turnos/reservas/{reserva.id}/cancelar",
        json={"motivo": "El vecino avisó por teléfono"},
        headers=headers_operador,
    )
    repetida = await client.post(
        f"/api/turnos/reservas/{reserva.id}/cancelar", json={}, headers=headers_operador
    )

    assert response.status_code == 200
    assert response.json()["estado"] == "cancelada"
    assert repetida.status_code == 409
    auditoria = (
        await db_session.execute(select(Auditoria).where(Auditoria.caso_id == reserva.caso_id))
    ).scalars().all()
    assert any(a.accion == "cancelacion_reserva" for a in auditoria)


async def test_registrar_asistencia(client, db_session, auth_headers, ciudadano):
    _, reserva = await _agenda_con_reserva(db_session, ciudadano)

    response = await client.post(
        f"/api/turnos/reservas/{reserva.id}/asistencia", json={"estado": "atendida"}, headers=auth_headers
    )
    invalida = await client.post(
        f"/api/turnos/reservas/{reserva.id}/asistencia", json={"estado": "cancelada"}, headers=auth_headers
    )

    assert response.json()["estado"] == "atendida"
    assert invalida.status_code == 422
