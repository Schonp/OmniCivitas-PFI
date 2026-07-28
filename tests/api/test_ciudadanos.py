import uuid

from app.db.crud.ciudadanos import (
    crear_ciudadano,
    obtener_ciudadano_por_email,
    obtener_ciudadano_por_telefono,
)
from app.schemas.ciudadano import CiudadanoCreate


async def test_crear_y_obtener_ciudadano(client, auth_headers):
    response = await client.post(
        "/api/ciudadanos",
        json={
            "documento": "12345678",
            "nombre": "Juana Pérez",
            "email": "juana@example.com",
            "telefono": "+5491111111111",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    ciudadano_id = response.json()["id"]

    response = await client.get(f"/api/ciudadanos/{ciudadano_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["documento"] == "12345678"


async def test_crear_ciudadano_sin_auth_falla(client):
    response = await client.post("/api/ciudadanos", json={"documento": "1", "nombre": "X"})

    assert response.status_code == 401


async def test_obtener_ciudadano_inexistente_404(client, auth_headers):
    response = await client.get(f"/api/ciudadanos/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404


async def test_buscar_ciudadano_por_telefono(db_session):
    creado = await crear_ciudadano(
        db_session,
        CiudadanoCreate(
            documento="99887766",
            nombre="Carlos Gómez",
            email="Carlos@Example.com",
            telefono="+5491122223333",
        ),
    )

    por_telefono = await obtener_ciudadano_por_telefono(db_session, "+5491122223333")
    # La normalización (strip + lower) debe hacer matchear variantes del email
    por_email = await obtener_ciudadano_por_email(db_session, "  carlos@example.com ")

    assert por_telefono is not None and por_telefono.id == creado.id
    assert por_email is not None and por_email.id == creado.id


async def test_buscar_ciudadano_por_telefono_inexistente(db_session):
    resultado = await obtener_ciudadano_por_telefono(db_session, "+5490000000000")

    assert resultado is None
