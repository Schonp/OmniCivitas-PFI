import uuid

from langchain_core.messages import AIMessage

from app.channels import whatsapp
from app.schemas.agente import ClasificacionIntent


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
        json={"ciudadano_id": ciudadano_id, "tipo": "consulta", "canal_origen": "whatsapp"},
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
        json={"ciudadano_id": ciudadano_id, "tipo": "tramite", "canal_origen": "voz"},
        headers=auth_headers,
    )

    response = await client.get("/api/casos", params={"estado": "abierto"}, headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) >= 1


async def test_listar_casos_incluye_ciudadano(client, auth_headers):
    ciudadano_id = await _crear_ciudadano(client, auth_headers, documento="20304051")
    await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )

    response = await client.get("/api/casos", headers=auth_headers)

    assert response.status_code == 200
    caso = response.json()[0]
    assert caso["ciudadano"]["nombre"] == "Carlos Gómez"
    assert caso["ciudadano"]["documento"] == "20304051"
    # El panel no muestra datos de contacto del ciudadano.
    assert "email" not in caso["ciudadano"]
    assert "telefono" not in caso["ciudadano"]


async def test_interacciones_de_caso_en_orden_cronologico(
    client, db_session, auth_headers, ciudadano, mock_llms, checkpointer_en_memoria
):
    """Las interacciones que el panel muestra son las que persiste el grafo."""
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "consulta", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Su caso está en revisión.")],
    )
    await whatsapp.recibir_mensaje(
        db_session, telefono=ciudadano.telefono, mensaje="¿Cómo sigue mi trámite?"
    )

    response = await client.get(f"/api/casos/{caso_id}/interacciones", headers=auth_headers)

    assert response.status_code == 200
    interacciones = response.json()
    assert [i["actor"] for i in interacciones] == ["ciudadano", "agente_ia"]
    assert interacciones[0]["contenido"] == "¿Cómo sigue mi trámite?"


async def _crear_caso(client, auth_headers, ciudadano_id: str, tipo: str = "reclamo") -> dict:
    respuesta = await client.post(
        "/api/casos",
        json={"ciudadano_id": ciudadano_id, "tipo": tipo, "canal_origen": "whatsapp"},
        headers=auth_headers,
    )
    return respuesta.json()


async def test_asignar_caso_a_operador_registra_auditoria(
    client, auth_headers, usuario_admin, ciudadano
):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))
    assert caso["operador_asignado"] is None

    response = await client.patch(
        f"/api/casos/{caso['id']}/asignacion",
        json={"operador_asignado_id": str(usuario_admin.id)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["operador_asignado"]["nombre"] == usuario_admin.nombre

    auditoria = await client.get(f"/api/casos/{caso['id']}/auditoria", headers=auth_headers)
    asignaciones = [e for e in auditoria.json() if e["accion"] == "asignacion"]
    assert asignaciones and asignaciones[0]["metadata"]["operador_nuevo"] == usuario_admin.nombre


async def test_liberar_caso_deja_operador_en_null(
    client, auth_headers, usuario_admin, ciudadano
):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))
    await client.patch(
        f"/api/casos/{caso['id']}/asignacion",
        json={"operador_asignado_id": str(usuario_admin.id)},
        headers=auth_headers,
    )

    response = await client.patch(
        f"/api/casos/{caso['id']}/asignacion",
        json={"operador_asignado_id": None},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["operador_asignado"] is None


async def test_asignar_operador_inexistente_404(client, auth_headers, ciudadano):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))

    response = await client.patch(
        f"/api/casos/{caso['id']}/asignacion",
        json={"operador_asignado_id": str(uuid.uuid4())},
        headers=auth_headers,
    )

    assert response.status_code == 404


async def test_responder_caso_crea_interaccion_de_operador(
    client, auth_headers, usuario_admin, ciudadano
):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))

    response = await client.post(
        f"/api/casos/{caso['id']}/respuesta",
        json={"contenido": "Ya derivamos su reclamo al área correspondiente."},
        headers=auth_headers,
    )

    assert response.status_code == 201
    interaccion = response.json()
    assert interaccion["actor"] == "operador"
    # La respuesta sale por el canal en el que el ciudadano está conversando.
    assert interaccion["canal"] == caso["canal_actual"]

    listado = await client.get(f"/api/casos/{caso['id']}/interacciones", headers=auth_headers)
    assert [i["actor"] for i in listado.json()] == ["operador"]

    auditoria = await client.get(f"/api/casos/{caso['id']}/auditoria", headers=auth_headers)
    respuestas = [e for e in auditoria.json() if e["accion"] == "respuesta_operador"]
    assert respuestas and respuestas[0]["actor"] == usuario_admin.email


async def test_responder_caso_cerrado_devuelve_422(client, auth_headers, ciudadano):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))
    await client.patch(
        f"/api/casos/{caso['id']}/estado",
        json={"estado": "cerrado", "motivo": "resuelto"},
        headers=auth_headers,
    )

    response = await client.post(
        f"/api/casos/{caso['id']}/respuesta",
        json={"contenido": "Mensaje tardío"},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_responder_caso_vacio_devuelve_422(client, auth_headers, ciudadano):
    caso = await _crear_caso(client, auth_headers, str(ciudadano.id))

    response = await client.post(
        f"/api/casos/{caso['id']}/respuesta", json={"contenido": ""}, headers=auth_headers
    )

    assert response.status_code == 422


async def test_acciones_de_caso_requieren_auth(client):
    caso_id = uuid.uuid4()
    asignacion = await client.patch(f"/api/casos/{caso_id}/asignacion", json={})
    respuesta = await client.post(f"/api/casos/{caso_id}/respuesta", json={"contenido": "hola"})

    assert asignacion.status_code == 401
    assert respuesta.status_code == 401


async def test_interacciones_de_caso_inexistente_404(client, auth_headers):
    response = await client.get(f"/api/casos/{uuid.uuid4()}/interacciones", headers=auth_headers)

    assert response.status_code == 404


async def test_interacciones_requieren_auth(client):
    response = await client.get(f"/api/casos/{uuid.uuid4()}/interacciones")

    assert response.status_code == 401


async def test_caso_inexistente_404(client, auth_headers):
    response = await client.get(f"/api/casos/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404


async def test_endpoints_casos_requieren_auth(client):
    response = await client.get("/api/casos")

    assert response.status_code == 401
