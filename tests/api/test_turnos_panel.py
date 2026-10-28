"""Gestión de turnos desde el panel: reservar, reprogramar, configurar la
agenda, bloquear días y mandar recordatorios."""

from datetime import time, timedelta

import pytest
from sqlalchemy import select

from app.db.crud.turnos import reservar
from app.db.models import Auditoria, Canal, Caso, Ciudadano, EstadoReserva, Reserva, TipoCaso, Turno
from tests.horarios import dia_habil, horario, momento


@pytest.fixture
async def agenda(db_session) -> Turno:
    turno = Turno(
        nombre="Renovación de DNI",
        descripcion="Centro de documentación.",
        sede="Sede comunal",
        hora_apertura=time(8, 0),
        hora_cierre=time(12, 0),
        cupos_por_horario=1,
    )
    db_session.add(turno)
    await db_session.commit()
    return turno


async def _turno_de(db_session, ciudadano, agenda, hora="9:00") -> Reserva:
    caso = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reserva, canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp
    )
    db_session.add(caso)
    await db_session.flush()
    reserva = await reservar(
        db_session, agenda_id=agenda.id, ciudadano_id=ciudadano.id, caso_id=caso.id, momento=momento(hora=hora)
    )
    await db_session.commit()
    return reserva


# --- Reserva cargada por el operador -----------------------------------------


async def test_el_operador_reserva_para_un_vecino_nuevo(client, db_session, headers_operador, agenda):
    response = await client.post(
        f"/api/turnos/{agenda.id}/reservas",
        json={"documento": "29888777", "nombre": "Rosa Méndez", "fecha_hora": horario(hora="10:00").replace(" ", "T")},
        headers=headers_operador,
    )

    assert response.status_code == 201
    datos = response.json()
    assert datos["ciudadano"]["nombre"] == "Rosa Méndez"
    assert datos["estado"] == "confirmada"
    caso = await db_session.get(Caso, datos["caso_id"])
    assert caso.canal_origen == Canal.voz


async def test_un_dni_nuevo_sin_nombre_no_se_reserva(client, headers_operador, agenda):
    response = await client.post(
        f"/api/turnos/{agenda.id}/reservas",
        json={"documento": "29888777", "fecha_hora": horario().replace(" ", "T")},
        headers=headers_operador,
    )
    assert response.status_code == 422


async def test_el_panel_respeta_las_mismas_reglas(client, db_session, headers_operador, agenda, ciudadano):
    await _turno_de(db_session, ciudadano, agenda, "10:00")

    response = await client.post(
        f"/api/turnos/{agenda.id}/reservas",
        json={"documento": "29888777", "nombre": "Rosa Méndez", "fecha_hora": horario(hora="10:00").replace(" ", "T")},
        headers=headers_operador,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["motivo"] == "Ese horario ya está completo."
    assert len(response.json()["detail"]["alternativas"]) == 3
    # El intento fallido no deja ni el caso ni la reserva a medias.
    casos = (await db_session.execute(select(Caso).join(Ciudadano).where(Ciudadano.documento == "29888777"))).all()
    assert casos == []


# --- Reprogramación ----------------------------------------------------------------


async def test_reprogramar_mueve_el_turno_y_libera_el_anterior(client, db_session, headers_operador, agenda, ciudadano):
    reserva = await _turno_de(db_session, ciudadano, agenda, "9:00")

    response = await client.post(
        f"/api/turnos/reservas/{reserva.id}/reprogramar",
        json={"fecha_hora": horario(hora="11:00").replace(" ", "T")},
        headers=headers_operador,
    )

    assert response.status_code == 200
    assert response.json()["fecha_hora"].startswith(dia_habil().isoformat())
    # El caso es el mismo: el número que tiene el vecino sigue valiendo.
    assert response.json()["caso_id"] == str(reserva.caso_id)
    auditoria = (await db_session.execute(select(Auditoria.accion).where(Auditoria.caso_id == reserva.caso_id))).scalars().all()
    assert "reprogramacion_reserva" in auditoria

    otro = Ciudadano(documento="29888777", nombre="Rosa Méndez")
    db_session.add(otro)
    await db_session.commit()
    libre = await _turno_de(db_session, otro, agenda, "9:00")
    assert libre.estado == EstadoReserva.confirmada


async def test_reprogramar_a_un_horario_completo_ofrece_alternativas(client, db_session, headers_operador, agenda, ciudadano):
    reserva = await _turno_de(db_session, ciudadano, agenda, "9:00")
    otro = Ciudadano(documento="29888777", nombre="Rosa Méndez")
    db_session.add(otro)
    await db_session.commit()
    await _turno_de(db_session, otro, agenda, "10:00")

    response = await client.post(
        f"/api/turnos/reservas/{reserva.id}/reprogramar",
        json={"fecha_hora": horario(hora="10:00").replace(" ", "T")},
        headers=headers_operador,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["alternativas"]


# --- Configuración de la agenda ----------------------------------------------------


async def test_el_supervisor_configura_la_agenda(client, auth_headers, agenda):
    response = await client.patch(
        f"/api/turnos/{agenda.id}",
        json={"hora_cierre": "13:00", "duracion_minutos": 20, "cupos_por_horario": 3, "dias_atencion": [0, 2, 4]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    datos = response.json()
    assert datos["hora_cierre"] == "13:00"
    assert datos["dias_atencion"] == [0, 2, 4]
    assert datos["horario"] == "los lunes, miércoles y viernes de 8:00 a 13:00, cada 20 minutos"


async def test_el_operador_no_configura_la_agenda(client, headers_operador, agenda):
    response = await client.patch(f"/api/turnos/{agenda.id}", json={"cupos_por_horario": 3}, headers=headers_operador)
    assert response.status_code == 403


async def test_la_apertura_tiene_que_ser_antes_del_cierre(client, auth_headers, agenda):
    response = await client.patch(f"/api/turnos/{agenda.id}", json={"hora_apertura": "13:00"}, headers=auth_headers)
    assert response.status_code == 422


# --- Días bloqueados ---------------------------------------------------------------


async def test_un_feriado_bloquea_el_dia_y_avisa_los_turnos_que_habia(
    client, db_session, auth_headers, agenda, ciudadano
):
    await _turno_de(db_session, ciudadano, agenda, "9:00")

    response = await client.post(
        "/api/turnos/bloqueos",
        json={"fecha": dia_habil().isoformat(), "motivo": "Feriado nacional"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert [a["ciudadano"]["nombre"] for a in response.json()["afectados"]] == [ciudadano.nombre]

    otro = Ciudadano(documento="29888777", nombre="Rosa Méndez")
    db_session.add(otro)
    await db_session.commit()
    rechazo = await client.post(
        f"/api/turnos/{agenda.id}/reservas",
        json={"documento": "29888777", "fecha_hora": horario(hora="11:00").replace(" ", "T")},
        headers=auth_headers,
    )
    assert rechazo.status_code == 409
    assert "no hay atención: Feriado nacional" in rechazo.json()["detail"]["motivo"]

    listado = await client.get(
        "/api/turnos", params={"desde": dia_habil().isoformat(), "dias": 1}, headers=auth_headers
    )
    datos = listado.json()[0]
    assert datos["capacidad"] == 0
    assert datos["bloqueos"][0]["motivo"] == "Feriado nacional"


async def test_desbloquear_vuelve_a_abrir_el_dia(client, auth_headers, agenda):
    creado = await client.post(
        "/api/turnos/bloqueos",
        json={"fecha": dia_habil().isoformat(), "motivo": "Capacitación", "turno_id": str(agenda.id)},
        headers=auth_headers,
    )
    repetido = await client.post(
        "/api/turnos/bloqueos",
        json={"fecha": dia_habil().isoformat(), "motivo": "Otra vez", "turno_id": str(agenda.id)},
        headers=auth_headers,
    )
    borrado = await client.delete(f"/api/turnos/bloqueos/{creado.json()['bloqueo']['id']}", headers=auth_headers)

    assert repetido.status_code == 409
    assert borrado.status_code == 204
    assert (await client.get("/api/turnos/bloqueos/proximos", headers=auth_headers)).json() == []


# --- Recordatorios -------------------------------------------------------------------


async def test_recordatorios_de_manana(client, db_session, auth_headers, agenda, ciudadano, mocker):
    from app.channels import salida

    enviar = mocker.patch.object(salida.whatsapp, "enviar_plantilla")
    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "seguimiento")
    reserva = await _turno_de(db_session, ciudadano, agenda, "9:00")

    response = await client.post(
        "/api/turnos/recordatorios", json={"fecha": dia_habil().isoformat()}, headers=auth_headers
    )
    repetido = await client.post(
        "/api/turnos/recordatorios", json={"fecha": dia_habil().isoformat()}, headers=auth_headers
    )

    assert response.json()["enviados"] == 1
    assert repetido.json()["total"] == 0
    texto = enviar.await_args.args[1]
    assert texto.startswith("Le recordamos su turno de Renovación de DNI para")
    assert "Sede comunal" in texto
    await db_session.refresh(reserva)
    assert reserva.recordatorio_enviado_en is not None


async def test_un_recordatorio_que_no_sale_se_reintenta(client, db_session, auth_headers, agenda, ciudadano, mocker):
    from app.channels import salida

    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "")
    reserva = await _turno_de(db_session, ciudadano, agenda, "9:00")

    response = await client.post(
        "/api/turnos/recordatorios", json={"fecha": dia_habil().isoformat()}, headers=auth_headers
    )

    assert response.json()["enviados"] == 0
    assert response.json()["no_enviados"][0]["motivo"] == "fuera_de_ventana"
    await db_session.refresh(reserva)
    assert reserva.recordatorio_enviado_en is None
