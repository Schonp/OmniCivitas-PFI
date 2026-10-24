"""Derechos del titular de los datos (Ley 25.326): acceso, rectificación y supresión."""

from sqlalchemy import select

from app.db.crud.interacciones import crear_interaccion
from app.db.crud.titulares import CONTENIDO_SUPRIMIDO, NOMBRE_SUPRIMIDO
from app.db.models import ActorInteraccion, Auditoria, Canal, Caso, Ciudadano, Interaccion, TipoCaso


async def _caso_con_conversacion(db_session, ciudadano) -> Caso:
    caso = Caso(ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo, canal_origen=Canal.whatsapp,
                canal_actual=Canal.whatsapp, asunto="Pozo", resumen_ia="Pozo frente a la casa de Juan")
    db_session.add(caso)
    await db_session.flush()
    await crear_interaccion(db_session, caso_id=caso.id, contenido="Hay un pozo frente a mi casa en Thames 1200",
                            canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano)
    await crear_interaccion(db_session, caso_id=caso.id, contenido="Registré su reclamo, Juan.",
                            canal=Canal.whatsapp, actor=ActorInteraccion.agente_ia)
    await db_session.commit()
    return caso


async def test_el_supervisor_exporta_todo_lo_que_se_guarda_del_titular(client, db_session, auth_headers, ciudadano):
    caso = await _caso_con_conversacion(db_session, ciudadano)

    respuesta = await client.get(f"/api/ciudadanos/{ciudadano.id}/datos", headers=auth_headers)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["titular"]["documento"] == ciudadano.documento
    assert datos["titular"]["email"] == ciudadano.email
    assert datos["finalidad"]
    assert datos["casos"][0]["referencia"] == caso.referencia
    assert [i["contenido"] for i in datos["casos"][0]["interacciones"]] == [
        "Hay un pozo frente a mi casa en Thames 1200", "Registré su reclamo, Juan.",
    ]


async def test_el_supervisor_rectifica_los_datos_y_queda_auditado_sin_el_dato(client, db_session, auth_headers, ciudadano):
    caso = await _caso_con_conversacion(db_session, ciudadano)

    respuesta = await client.patch(
        f"/api/ciudadanos/{ciudadano.id}", json={"nombre": "Juan Carlos Pérez", "email": "nuevo@correo.test"},
        headers=auth_headers,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Juan Carlos Pérez"
    assert respuesta.json()["email"] == "nuevo@correo.test"
    entrada = (await db_session.execute(
        select(Auditoria).where(Auditoria.caso_id == caso.id, Auditoria.accion == "rectificacion_datos_titular")
    )).scalar_one()
    assert entrada.metadata_ == {"campos": ["nombre", "email"]}


async def test_la_baja_borra_los_datos_y_anonimiza_el_historial(client, db_session, auth_headers, ciudadano):
    caso = await _caso_con_conversacion(db_session, ciudadano)

    respuesta = await client.post(f"/api/ciudadanos/{ciudadano.id}/baja", headers=auth_headers)

    assert respuesta.status_code == 204
    titular = (
        await db_session.execute(
            select(Ciudadano).where(Ciudadano.id == ciudadano.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert titular.nombre == NOMBRE_SUPRIMIDO
    assert titular.email is None and titular.telefono is None
    assert titular.documento.startswith("BAJA-")
    contenidos = (await db_session.execute(select(Interaccion.contenido).where(Interaccion.caso_id == caso.id))).scalars().all()
    assert set(contenidos) == {CONTENIDO_SUPRIMIDO}
    resumen, asunto = (await db_session.execute(select(Caso.resumen_ia, Caso.asunto).where(Caso.id == caso.id))).one()
    assert resumen is None and asunto is None
    # El caso y su auditoría se conservan, con la baja registrada.
    acciones = (await db_session.execute(select(Auditoria.accion).where(Auditoria.caso_id == caso.id))).scalars().all()
    assert "baja_datos_titular" in acciones


async def test_un_operador_no_puede_exportar_ni_dar_de_baja(client, headers_operador, ciudadano):
    assert (await client.get(f"/api/ciudadanos/{ciudadano.id}/datos", headers=headers_operador)).status_code == 403
    assert (await client.post(f"/api/ciudadanos/{ciudadano.id}/baja", headers=headers_operador)).status_code == 403
    assert (await client.patch(f"/api/ciudadanos/{ciudadano.id}", json={"nombre": "X"}, headers=headers_operador)).status_code == 403
