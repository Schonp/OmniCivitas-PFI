"""Avisos del panel: los casos que llegan a la bandeja de quien está mirando."""

import uuid
from datetime import datetime, timedelta, timezone

from app.agents.escalado import escalar_caso_por_falla


async def _crear_caso(client, auth_headers, ciudadano) -> str:
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )
    return creado.json()["id"]


async def _avisos(client, headers, desde: str | None):
    params = {"desde": desde} if desde else {}
    return await client.get("/api/casos/avisos", params=params, headers=headers)


async def test_sin_desde_solo_devuelve_la_hora(client, auth_headers):
    response = await _avisos(client, auth_headers, None)

    assert response.status_code == 200
    assert response.json()["avisos"] == []
    assert response.json()["ahora"]


async def test_supervisor_recibe_la_derivacion_aunque_ya_este_asignada(
    client, db_session, auth_headers, usuario_operador, ciudadano
):
    desde = (await _avisos(client, auth_headers, None)).json()["ahora"]
    caso_id = await _crear_caso(client, auth_headers, ciudadano)

    # Al derivar se asigna en el acto: el caso queda en progreso, no escalado.
    await escalar_caso_por_falla(db_session, uuid.UUID(caso_id), "envio_fallido")

    avisos = (await _avisos(client, auth_headers, desde)).json()["avisos"]
    assert [(a["caso"]["id"], a["motivo"]) for a in avisos] == [(caso_id, "derivado")]
    assert avisos[0]["caso"]["estado"] == "en_progreso"


async def test_no_avisa_lo_anterior_a_desde(
    client, db_session, auth_headers, usuario_operador, ciudadano
):
    caso_id = await _crear_caso(client, auth_headers, ciudadano)
    await escalar_caso_por_falla(db_session, uuid.UUID(caso_id), "envio_fallido")
    desde = (await _avisos(client, auth_headers, None)).json()["ahora"]

    avisos = (await _avisos(client, auth_headers, desde)).json()["avisos"]

    assert avisos == []


async def test_operador_recibe_solo_los_casos_que_le_asignaron(
    client, auth_headers, headers_operador, usuario_operador, ciudadano
):
    desde = (await _avisos(client, headers_operador, None)).json()["ahora"]
    propio = await _crear_caso(client, auth_headers, ciudadano)
    await _crear_caso(client, auth_headers, ciudadano)
    await client.patch(
        f"/api/casos/{propio}/asignacion",
        json={"operador_asignado_id": str(usuario_operador.id)},
        headers=auth_headers,
    )

    del_operador = (await _avisos(client, headers_operador, desde)).json()["avisos"]
    del_supervisor = (await _avisos(client, auth_headers, desde)).json()["avisos"]

    assert [(a["caso"]["id"], a["motivo"]) for a in del_operador] == [(propio, "asignado")]
    # Una asignación a mano no es una derivación: el supervisor no la necesita.
    assert del_supervisor == []


async def test_un_caso_cerrado_no_avisa(
    client, db_session, auth_headers, usuario_operador, ciudadano
):
    desde = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    caso_id = await _crear_caso(client, auth_headers, ciudadano)
    await escalar_caso_por_falla(db_session, uuid.UUID(caso_id), "envio_fallido")
    await client.patch(
        f"/api/casos/{caso_id}/estado",
        json={"estado": "cerrado", "motivo": "resuelto"},
        headers=auth_headers,
    )

    avisos = (await _avisos(client, auth_headers, desde)).json()["avisos"]

    assert avisos == []
