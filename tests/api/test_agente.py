async def test_enviar_mensaje_sin_token_devuelve_401(client):
    response = await client.post(
        "/api/agente/mensaje",
        json={"mensaje": "hola", "canal": "whatsapp", "identificador": "+549112233"},
    )
    assert response.status_code == 401


async def test_enviar_mensaje_payload_invalido_devuelve_422(client, auth_headers):
    response = await client.post(
        "/api/agente/mensaje",
        json={"mensaje": "", "canal": "paloma", "identificador": ""},
        headers=auth_headers,
    )
    assert response.status_code == 422
