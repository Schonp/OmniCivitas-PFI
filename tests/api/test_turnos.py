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
