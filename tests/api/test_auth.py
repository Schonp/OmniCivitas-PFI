async def test_registrar_primer_usuario_es_supervisor_bootstrap(client):
    response = await client.post(
        "/api/auth/registrar",
        json={
            "email": "primero@omnicivitas.test",
            "nombre": "Primero",
            "password": "password123",
            "rol": "operador",
        },
    )

    assert response.status_code == 201
    assert response.json()["rol"] == "supervisor"


async def test_login_devuelve_tokens(client, usuario_admin):
    response = await client.post(
        "/api/auth/login",
        json={"email": usuario_admin.email, "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_password_incorrecta(client, usuario_admin):
    response = await client.post(
        "/api/auth/login",
        json={"email": usuario_admin.email, "password": "incorrecta"},
    )

    assert response.status_code == 401


async def test_refresh_devuelve_nuevo_access_token(client, usuario_admin):
    login = await client.post(
        "/api/auth/login",
        json={"email": usuario_admin.email, "password": "password123"},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_registrar_usuario_sin_token_falla_si_ya_hay_usuarios(client, usuario_admin):
    response = await client.post(
        "/api/auth/registrar",
        json={"email": "nuevo@omnicivitas.test", "nombre": "Nuevo", "password": "password123"},
    )

    assert response.status_code == 401


async def test_registrar_usuario_con_admin_autenticado(client, usuario_admin, auth_headers):
    response = await client.post(
        "/api/auth/registrar",
        json={
            "email": "operador2@omnicivitas.test",
            "nombre": "Operador Dos",
            "password": "password123",
            "rol": "operador",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["rol"] == "operador"
