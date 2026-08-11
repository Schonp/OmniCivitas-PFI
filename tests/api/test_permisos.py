"""Reglas de rol: el operador trabaja su bandeja, el supervisor ve todo."""

import uuid


async def _crear_caso(client, auth_headers, ciudadano_id: str) -> dict:
    respuesta = await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )
    return respuesta.json()


async def _asignar(client, auth_headers, caso_id: str, usuario_id: str):
    return await client.patch(
        f"/api/casos/{caso_id}/asignacion",
        json={"operador_asignado_id": usuario_id},
        headers=auth_headers,
    )


async def test_operador_no_puede_crear_casos(client, headers_operador, ciudadano):
    response = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=headers_operador,
    )
    assert response.status_code == 403


async def test_operador_no_puede_reasignar(
    client, auth_headers, headers_operador, usuario_operador, ciudadano
):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))

    response = await _asignar(client, headers_operador, caso["id"], str(usuario_operador.id))

    assert response.status_code == 403


async def test_operador_solo_ve_sus_casos(
    client, auth_headers, headers_operador, usuario_operador, ciudadano
):
    propio = await _crear_caso(client, auth_headers, str(ciudadano.id))
    ajeno = await _crear_caso(client, auth_headers, str(ciudadano.id))
    await _asignar(client, auth_headers, propio["id"], str(usuario_operador.id))

    del_operador = await client.get("/api/casos", headers=headers_operador)
    del_supervisor = await client.get("/api/casos", headers=auth_headers)

    assert [caso["id"] for caso in del_operador.json()] == [propio["id"]]
    assert {caso["id"] for caso in del_supervisor.json()} == {propio["id"], ajeno["id"]}


async def test_operador_no_accede_a_caso_ajeno(client, auth_headers, headers_operador, ciudadano):
    ajeno = await _crear_caso(client, auth_headers, str(ciudadano.id))

    detalle = await client.get(f"/api/casos/{ajeno['id']}", headers=headers_operador)
    interacciones = await client.get(
        f"/api/casos/{ajeno['id']}/interacciones", headers=headers_operador
    )
    auditoria = await client.get(f"/api/casos/{ajeno['id']}/auditoria", headers=headers_operador)

    # 404 y no 403: confirmar que el caso existe ya filtraría datos del ciudadano.
    assert detalle.status_code == 404
    assert interacciones.status_code == 404
    assert auditoria.status_code == 404


async def test_operador_gestiona_su_propio_caso(
    client, auth_headers, headers_operador, usuario_operador, ciudadano
):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))
    await _asignar(client, auth_headers, caso["id"], str(usuario_operador.id))

    respuesta = await client.post(
        f"/api/casos/{caso['id']}/respuesta",
        json={"contenido": "Estamos viendo su reclamo."},
        headers=headers_operador,
    )
    estado = await client.patch(
        f"/api/casos/{caso['id']}/estado",
        json={"estado": "en_progreso"},
        headers=headers_operador,
    )

    assert respuesta.status_code == 201
    assert estado.status_code == 200


async def test_operador_no_lista_usuarios(client, headers_operador):
    response = await client.get("/api/usuarios", headers=headers_operador)
    assert response.status_code == 403


async def test_supervisor_lista_usuarios(client, auth_headers, usuario_operador):
    response = await client.get("/api/usuarios", headers=auth_headers)

    assert response.status_code == 200
    assert any(usuario["email"] == usuario_operador.email for usuario in response.json())


async def test_operador_no_exporta(client, headers_operador):
    response = await client.get("/api/casos/exportar", headers=headers_operador)
    assert response.status_code == 403


async def test_supervisor_exporta_csv(client, auth_headers, ciudadano):
    await _crear_caso(client, auth_headers, str(ciudadano.id))

    response = await client.get("/api/casos/exportar", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "caso_id;ciudadano;documento" in response.text
    assert ciudadano.documento in response.text


async def test_asignar_caso_inexistente_404(client, auth_headers, usuario_operador):
    response = await _asignar(client, auth_headers, str(uuid.uuid4()), str(usuario_operador.id))
    assert response.status_code == 404
