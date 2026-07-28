import uuid


async def _crear_ciudadano(client, auth_headers, documento: str = "20304050") -> str:
    response = await client.post(
        "/api/ciudadanos",
        json={"documento": documento, "nombre": "Carlos Gómez"},
        headers=auth_headers,
    )
    return response.json()["id"]


async def test_crear_caso_registra_auditoria(client, auth_headers):
    ciudadano_id = await _crear_ciudadano(client, auth_headers)

    response = await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    caso = response.json()
    assert caso["estado"] == "abierto"
    assert caso["canal_actual"] == "whatsapp"

    response = await client.get(f"/api/casos/{caso['id']}/auditoria", headers=auth_headers)

    assert response.status_code == 200
    assert any(entrada["accion"] == "creacion" for entrada in response.json())


async def test_crear_caso_ciudadano_inexistente_404(client, auth_headers):
    response = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(uuid.uuid4()), "tipo": "consulta", "canal_origen": "email"},
        headers=auth_headers,
    )

    assert response.status_code == 404


async def test_cambio_estado_caso_registra_auditoria(client, auth_headers):
    ciudadano_id = await _crear_ciudadano(client, auth_headers)
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": "consulta", "canal_origen": "web"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    response = await client.patch(
        f"/api/casos/{caso_id}/estado",
        json={"estado": "en_progreso"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["estado"] == "en_progreso"

    response = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    assert any(entrada["accion"] == "cambio_estado" for entrada in response.json())


async def test_listar_casos_filtra_por_estado(client, auth_headers):
    ciudadano_id = await _crear_ciudadano(client, auth_headers)
    await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": "tramite", "canal_origen": "sms"},
        headers=auth_headers,
    )

    response = await client.get("/api/casos", params={"estado": "abierto"}, headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) >= 1


async def test_caso_inexistente_404(client, auth_headers):
    response = await client.get(f"/api/casos/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404


async def test_endpoints_casos_requieren_auth(client):
    response = await client.get("/api/casos")

    assert response.status_code == 401
