"""Ficha del ciudadano: sus casos en todos los canales, con la visibilidad del rol."""

import uuid

from app.db.models import ActorInteraccion, Canal, Interaccion


async def _crear_caso(client, auth_headers, ciudadano, canal="whatsapp", tipo="reclamo") -> str:
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": tipo, "canal_origen": canal},
        headers=auth_headers,
    )
    return creado.json()["id"]


async def _asignar(client, auth_headers, caso_id: str, usuario_id: str):
    await client.patch(
        f"/api/casos/{caso_id}/asignacion",
        json={"operador_asignado_id": usuario_id},
        headers=auth_headers,
    )


def _mensaje(caso_id: str, contenido: str, canal=Canal.whatsapp, interna=False):
    return Interaccion(
        caso_id=caso_id,
        contenido=contenido,
        canal=canal,
        actor=ActorInteraccion.operador if interna else ActorInteraccion.ciudadano,
        interna=interna,
    )


async def test_ficha_junta_los_casos_de_todos_los_canales(
    client, db_session, auth_headers, ciudadano
):
    reclamo = await _crear_caso(client, auth_headers, ciudadano)
    consulta = await _crear_caso(client, auth_headers, ciudadano, canal="email", tipo="consulta")
    db_session.add(_mensaje(reclamo, "Hay un pozo en Rivadavia 3200"))
    await db_session.commit()
    db_session.add(_mensaje(reclamo, "¿Cómo va el pozo?", canal=Canal.email))
    await db_session.commit()
    db_session.add(_mensaje(consulta, "¿Qué necesito para la licencia?", canal=Canal.email))
    await db_session.commit()

    response = await client.get(f"/api/ciudadanos/{ciudadano.id}/ficha", headers=auth_headers)

    assert response.status_code == 200
    ficha = response.json()
    assert ficha["nombre"] == ciudadano.nombre
    assert ficha["identificado"] is True
    assert ficha["canales"] == ["whatsapp", "email"]
    # Del más reciente al más viejo.
    assert [c["id"] for c in ficha["casos"]] == [consulta, reclamo]
    del_reclamo = ficha["casos"][1]
    assert del_reclamo["mensajes"] == 2
    assert del_reclamo["recorrido"] == ["whatsapp", "email"]
    assert del_reclamo["ultimo_mensaje"]["contenido"] == "¿Cómo va el pozo?"
    assert ficha["ultimo_contacto"] is not None


async def test_ficha_no_trae_datos_de_contacto(client, auth_headers, ciudadano):
    await _crear_caso(client, auth_headers, ciudadano)

    response = await client.get(f"/api/ciudadanos/{ciudadano.id}/ficha", headers=auth_headers)

    texto = response.text
    assert ciudadano.email not in texto
    assert ciudadano.telefono not in texto


async def test_ficha_no_cuenta_notas_internas(client, db_session, auth_headers, ciudadano):
    caso = await _crear_caso(client, auth_headers, ciudadano)
    db_session.add(_mensaje(caso, "Se cortó la luz en la cuadra"))
    await db_session.commit()
    db_session.add(_mensaje(caso, "Vecino conflictivo.", interna=True))
    await db_session.commit()

    response = await client.get(f"/api/ciudadanos/{ciudadano.id}/ficha", headers=auth_headers)

    del_caso = response.json()["casos"][0]
    assert del_caso["mensajes"] == 1
    assert del_caso["ultimo_mensaje"]["contenido"] == "Se cortó la luz en la cuadra"


async def test_operador_ve_la_ficha_sin_el_contenido_de_casos_ajenos(
    client, db_session, auth_headers, headers_operador, usuario_operador, ciudadano
):
    propio = await _crear_caso(client, auth_headers, ciudadano)
    ajeno = await _crear_caso(client, auth_headers, ciudadano)
    await _asignar(client, auth_headers, propio, str(usuario_operador.id))
    db_session.add_all([_mensaje(propio, "Mensaje del propio"), _mensaje(ajeno, "Mensaje del ajeno")])
    await db_session.commit()

    response = await client.get(f"/api/ciudadanos/{ciudadano.id}/ficha", headers=headers_operador)

    assert response.status_code == 200
    casos = {c["id"]: c for c in response.json()["casos"]}
    assert casos[propio]["puede_abrir"] is True
    assert casos[propio]["ultimo_mensaje"]["contenido"] == "Mensaje del propio"
    assert casos[ajeno]["puede_abrir"] is False
    assert casos[ajeno]["ultimo_mensaje"] is None
    assert "Mensaje del ajeno" not in response.text


async def test_operador_sin_casos_del_vecino_recibe_404(
    client, auth_headers, headers_operador, ciudadano
):
    await _crear_caso(client, auth_headers, ciudadano)

    response = await client.get(f"/api/ciudadanos/{ciudadano.id}/ficha", headers=headers_operador)

    assert response.status_code == 404


async def test_ficha_de_ciudadano_inexistente_devuelve_404(client, auth_headers):
    response = await client.get(f"/api/ciudadanos/{uuid.uuid4()}/ficha", headers=auth_headers)

    assert response.status_code == 404
