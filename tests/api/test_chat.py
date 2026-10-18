import uuid

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.agents.graph import procesar_mensaje
from app.core.security import crear_chat_token
from app.db.models import Auditoria, Canal, Caso, Ciudadano
from app.schemas.agente import ClasificacionIntent

RECLAMO = ClasificacionIntent(
    intencion="reclamo", entidades={"categoria": "infraestructura"}, confianza=0.9
)
CONSULTA = ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9)

TOOL_CALL_RECLAMO = AIMessage(
    content="",
    tool_calls=[
        {
            "name": "crear_reclamo",
            "args": {"descripcion": "La vereda está rota", "categoria": "infraestructura"},
            "id": "tc1",
            "type": "tool_call",
        }
    ],
)


async def _abrir_sesion(client, *, documento="12345678", nombre="Juan Pérez", **contacto):
    payload = {"documento": documento, "nombre": nombre, **contacto}
    payload.setdefault("email", "juan.perez@test.com")
    response = await client.post("/api/chat/sesion", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_iniciar_sesion_da_de_alta_ciudadano_nuevo(client, db_session):
    response = await client.post(
        "/api/chat/sesion",
        json={"documento": "40555666", "nombre": "Lucía Díaz", "email": "lucia@test.com"},
    )

    assert response.status_code == 201
    cuerpo = response.json()
    assert cuerpo["token"]
    assert cuerpo["nombre"] == "Lucía Díaz"

    creado = await db_session.get(Ciudadano, uuid.UUID(cuerpo["ciudadano_id"]))
    assert creado is not None


async def test_iniciar_sesion_reutiliza_ciudadano_por_documento(client, ciudadano):
    sesion = await _abrir_sesion(client)
    assert sesion["ciudadano_id"] == str(ciudadano.id)


async def test_iniciar_sesion_sin_contacto_devuelve_422(client):
    response = await client.post(
        "/api/chat/sesion", json={"documento": "40555666", "nombre": "Lucía Díaz"}
    )
    assert response.status_code == 422


async def test_enviar_mensaje_sin_sesion_devuelve_401(client):
    response = await client.post("/api/chat/mensaje", json={"mensaje": "hola"})
    assert response.status_code == 401


async def test_enviar_mensaje_con_token_de_operador_devuelve_401(client, auth_headers):
    """Un token del panel (tipo access) no habilita el canal ciudadano."""
    response = await client.post(
        "/api/chat/mensaje", json={"mensaje": "hola"}, headers=auth_headers
    )
    assert response.status_code == 401


async def test_enviar_mensaje_de_ciudadano_inexistente_devuelve_401(client):
    token = crear_chat_token(str(uuid.uuid4()))
    response = await client.post(
        "/api/chat/mensaje",
        json={"mensaje": "hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


async def test_enviar_mensaje_resuelve_caso_y_audita(
    client, db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms(
        RECLAMO,
        respuestas_ejecutor=[
            TOOL_CALL_RECLAMO,
            AIMessage(content="Su reclamo fue registrado."),
        ],
    )
    sesion = await _abrir_sesion(client)

    response = await client.post(
        "/api/chat/mensaje",
        json={"mensaje": "La vereda de mi cuadra está rota"},
        headers={"Authorization": f"Bearer {sesion['token']}"},
    )

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["respuesta"].endswith("Su reclamo fue registrado.")
    assert cuerpo["escalado"] is False

    caso = await db_session.get(Caso, uuid.UUID(cuerpo["caso_id"]))
    assert caso.canal_origen == Canal.web

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert "respuesta_ia" in {a.accion for a in auditorias}


async def test_historial_continua_caso_abierto_en_otro_canal(
    client, db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El caso nace en WhatsApp y el ciudadano lo retoma por el chat web:
    mismo caso, historial completo y cambio de canal auditado."""
    mock_llms(
        [RECLAMO, CONSULTA],
        respuestas_ejecutor=[
            TOOL_CALL_RECLAMO,
            AIMessage(content="Su reclamo fue registrado."),
            AIMessage(content="Su reclamo sigue en revisión."),
        ],
    )

    inicial = await procesar_mensaje(
        db_session,
        mensaje="La vereda de mi barrio está rota",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=InMemorySaver(),
    )
    caso_id = inicial["caso_id"]

    sesion = await _abrir_sesion(client)
    headers = {"Authorization": f"Bearer {sesion['token']}"}
    respuesta = await client.post(
        "/api/chat/mensaje", json={"mensaje": "¿Cómo va mi reclamo?"}, headers=headers
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["caso_id"] == caso_id

    historial = await client.get("/api/chat/historial", headers=headers)
    assert historial.status_code == 200
    cuerpo = historial.json()
    assert cuerpo["caso_id"] == caso_id
    canales = {i["canal"] for i in cuerpo["interacciones"]}
    assert canales == {"whatsapp", "web"}

    caso = await db_session.get(Caso, uuid.UUID(caso_id))
    await db_session.refresh(caso)
    assert caso.canal_actual == Canal.web

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    cambios = [a for a in auditorias if a.accion == "cambio_canal"]
    assert cambios and cambios[0].metadata_ == {
        "canal_anterior": "whatsapp",
        "canal_nuevo": "web",
    }


async def test_historial_sin_caso_abierto_devuelve_vacio(client, ciudadano):
    sesion = await _abrir_sesion(client)
    response = await client.get(
        "/api/chat/historial", headers={"Authorization": f"Bearer {sesion['token']}"}
    )

    assert response.status_code == 200
    assert response.json() == {"caso_id": None, "estado": None, "interacciones": []}


async def test_sesion_supera_rate_limit_devuelve_429(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    payload = {"documento": "40555666", "nombre": "Lucía Díaz", "email": "lucia@test.com"}

    codigos = []
    for _ in range(3):
        codigos.append((await client.post("/api/chat/sesion", json=payload)).status_code)

    assert codigos == [201, 201, 429]


@pytest.mark.parametrize("mensaje", ["", "x" * 2001])
async def test_enviar_mensaje_invalido_devuelve_422(client, ciudadano, mensaje):
    sesion = await _abrir_sesion(client)
    response = await client.post(
        "/api/chat/mensaje",
        json={"mensaje": mensaje},
        headers={"Authorization": f"Bearer {sesion['token']}"},
    )
    assert response.status_code == 422
