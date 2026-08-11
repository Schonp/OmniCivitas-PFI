"""Base de conocimiento: carga de contexto para la IA y su recuperación."""

from app.agents.contexto import buscar_conocimiento
from app.db.models import Turno


async def test_crear_listar_y_borrar_documento(client, auth_headers):
    creado = await client.post(
        "/api/conocimiento",
        json={
            "titulo": "Requisitos para renovar la licencia",
            "contenido": "Licencia anterior, DNI y boleta paga.",
            "nombre_archivo": "licencia.txt",
        },
        headers=auth_headers,
    )
    assert creado.status_code == 201

    listado = await client.get("/api/conocimiento", headers=auth_headers)
    assert [d["titulo"] for d in listado.json()] == ["Requisitos para renovar la licencia"]

    borrado = await client.delete(
        f"/api/conocimiento/{creado.json()['id']}", headers=auth_headers
    )
    assert borrado.status_code == 204
    assert (await client.get("/api/conocimiento", headers=auth_headers)).json() == []


async def test_operador_puede_leer_pero_no_cargar(client, auth_headers, headers_operador):
    lectura = await client.get("/api/conocimiento", headers=headers_operador)
    escritura = await client.post(
        "/api/conocimiento",
        json={"titulo": "x", "contenido": "y"},
        headers=headers_operador,
    )

    assert lectura.status_code == 200
    assert escritura.status_code == 403


async def test_conocimiento_relevante_entra_al_contexto(client, db_session, auth_headers):
    await client.post(
        "/api/conocimiento",
        json={
            "titulo": "Renovación de licencia de conducir",
            "contenido": "Requiere licencia anterior, DNI vigente y boleta paga.",
        },
        headers=auth_headers,
    )
    await client.post(
        "/api/conocimiento",
        json={"titulo": "Poda de árboles", "contenido": "Se solicita en la comuna."},
        headers=auth_headers,
    )

    fragmentos = await buscar_conocimiento(
        db_session, "consulta", "¿Qué necesito para renovar la licencia de conducir?"
    )

    assert any("licencia anterior" in fragmento for fragmento in fragmentos)
    assert not any("Poda" in fragmento for fragmento in fragmentos)


async def test_intencion_reserva_agrega_turnos_disponibles(db_session):
    db_session.add(Turno(nombre="Renovación de DNI", descripcion="Documentación."))
    await db_session.commit()

    fragmentos = await buscar_conocimiento(db_session, "reserva", "quiero un turno")

    assert any("Turnos disponibles" in f and "Renovación de DNI" in f for f in fragmentos)
