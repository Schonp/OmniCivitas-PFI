"""Bandeja del panel: búsqueda, paginación, espera sin responder y notas internas."""

from datetime import datetime, timedelta, timezone

from app.db.models import (
    ActorInteraccion,
    Canal,
    Caso,
    Ciudadano,
    EstadoCaso,
    Interaccion,
    TipoCaso,
)

AHORA = datetime.now(timezone.utc)


async def _caso_con_ciudadano(db_session, nombre: str, documento: str) -> Caso:
    persona = Ciudadano(documento=documento, nombre=nombre, email=f"{documento}@test.com")
    db_session.add(persona)
    await db_session.flush()

    caso = Caso(
        ciudadano_id=persona.id,
        tipo=TipoCaso.consulta,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    return caso


async def test_busqueda_por_nombre_y_documento(client, db_session, auth_headers):
    await _caso_con_ciudadano(db_session, "Ana Gómez", "30111222")
    await _caso_con_ciudadano(db_session, "Beto Suárez", "30333444")
    await db_session.commit()

    por_nombre = await client.get("/api/casos", params={"q": "Gómez"}, headers=auth_headers)
    por_documento = await client.get("/api/casos", params={"q": "30333"}, headers=auth_headers)

    assert [c["ciudadano"]["nombre"] for c in por_nombre.json()] == ["Ana Gómez"]
    assert [c["ciudadano"]["nombre"] for c in por_documento.json()] == ["Beto Suárez"]


async def test_paginacion_devuelve_total_en_header(client, db_session, auth_headers):
    for indice in range(3):
        await _caso_con_ciudadano(db_session, f"Persona {indice}", f"4000000{indice}")
    await db_session.commit()

    response = await client.get("/api/casos", params={"limite": 2}, headers=auth_headers)

    assert len(response.json()) == 2
    assert response.headers["x-total-count"] == "3"


async def test_filtro_sin_asignar(client, db_session, auth_headers, usuario_operador):
    asignado = await _caso_con_ciudadano(db_session, "Con dueño", "50111222")
    await _caso_con_ciudadano(db_session, "Sin dueño", "50333444")
    asignado.operador_asignado_id = usuario_operador.id
    await db_session.commit()

    response = await client.get(
        "/api/casos", params={"sin_asignar": "true"}, headers=auth_headers
    )

    assert [c["ciudadano"]["nombre"] for c in response.json()] == ["Sin dueño"]


async def test_conteos_del_operador_solo_cuentan_su_bandeja(
    client, db_session, headers_operador, usuario_operador
):
    propio = await _caso_con_ciudadano(db_session, "Del operador", "70111222")
    propio.operador_asignado_id = usuario_operador.id
    await _caso_con_ciudadano(db_session, "Ajeno uno", "70333444")
    await _caso_con_ciudadano(db_session, "Ajeno dos", "70555666")
    await db_session.commit()

    cuerpo = (await client.get("/api/casos/conteos", headers=headers_operador)).json()

    assert cuerpo["todos"] == 1
    assert cuerpo["por_estado"] == {"abierto": 1}


async def test_conteos_del_supervisor_cuentan_todo_el_organismo(
    client, db_session, auth_headers, usuario_operador
):
    propio = await _caso_con_ciudadano(db_session, "Asignado", "71111222")
    propio.operador_asignado_id = usuario_operador.id
    await _caso_con_ciudadano(db_session, "Sin asignar", "71333444")
    await db_session.commit()

    cuerpo = (await client.get("/api/casos/conteos", headers=auth_headers)).json()

    assert cuerpo["todos"] == 2
    assert cuerpo["por_estado"] == {"abierto": 2}


async def test_esperando_desde_marca_el_mensaje_sin_responder(
    client, db_session, auth_headers
):
    caso = await _caso_con_ciudadano(db_session, "Espera", "60111222")
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="¿Hay novedades?",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
            timestamp=AHORA - timedelta(hours=30),
        )
    )
    await db_session.commit()

    response = await client.get("/api/casos", headers=auth_headers)

    assert response.json()[0]["esperando_desde"] is not None


async def test_un_caso_derivado_sigue_esperando_aunque_el_agente_haya_contestado(
    client, db_session, auth_headers
):
    """El acuse automático no es una respuesta: mientras el caso esté en manos
    de una persona, lo que se espera es lo que diga esa persona. Antes el aviso
    de derivación alcanzaba para que el caso figurara atendido y se fuera de la
    bandeja sin que nadie lo hubiera mirado."""
    caso = await _caso_con_ciudadano(db_session, "Derivada", "60555666")
    caso.estado = EstadoCaso.escalado
    db_session.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Necesito renovar la licencia",
                canal=Canal.email,
                actor=ActorInteraccion.ciudadano,
                timestamp=AHORA - timedelta(hours=5),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Lo pongo en contacto con una persona del equipo.",
                canal=Canal.email,
                actor=ActorInteraccion.agente_ia,
                timestamp=AHORA - timedelta(hours=5),
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/casos", headers=auth_headers)

    assert response.json()[0]["esperando_desde"] is not None


async def test_un_caso_derivado_deja_de_esperar_cuando_contesta_el_operador(
    client, db_session, auth_headers
):
    caso = await _caso_con_ciudadano(db_session, "Atendida", "60777888")
    caso.estado = EstadoCaso.escalado
    db_session.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Necesito renovar la licencia",
                canal=Canal.email,
                actor=ActorInteraccion.ciudadano,
                timestamp=AHORA - timedelta(hours=5),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Buenas tardes, le explico cómo seguir.",
                canal=Canal.email,
                actor=ActorInteraccion.operador,
                timestamp=AHORA - timedelta(hours=1),
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/casos", headers=auth_headers)

    assert response.json()[0]["esperando_desde"] is None


async def test_esperando_desde_es_null_si_ya_respondieron(client, db_session, auth_headers):
    caso = await _caso_con_ciudadano(db_session, "Respondida", "60333444")
    db_session.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="¿Hay novedades?",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.ciudadano,
                timestamp=AHORA - timedelta(hours=3),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Sí, ya se resolvió.",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.agente_ia,
                timestamp=AHORA - timedelta(hours=2),
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/casos", headers=auth_headers)

    assert response.json()[0]["esperando_desde"] is None


async def test_metrica_cuenta_casos_demorados(client, db_session, auth_headers):
    caso = await _caso_con_ciudadano(db_session, "Demorada", "60555666")
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="Sigo esperando",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
            timestamp=AHORA - timedelta(hours=48),
        )
    )
    await db_session.commit()

    cuerpo = (await client.get("/api/metricas", headers=auth_headers)).json()

    assert cuerpo["casos_esperando_respuesta"] == 1
    assert cuerpo["casos_demorados"] == 1
    assert cuerpo["horas_umbral_demora"] == 24


async def test_nota_interna_no_llega_al_ciudadano(client, db_session, auth_headers, ciudadano):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "web"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Ojo: el vecino ya reclamó tres veces.", "interna": True},
        headers=auth_headers,
    )
    await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Su reclamo está en revisión."},
        headers=auth_headers,
    )

    del_panel = await client.get(f"/api/casos/{caso_id}/interacciones", headers=auth_headers)
    assert [i["interna"] for i in del_panel.json()] == [True, False]

    sesion = await client.post(
        "/api/chat/sesion",
        json={"documento": ciudadano.documento, "nombre": ciudadano.nombre, "email": ciudadano.email},
    )
    historial = await client.get(
        "/api/chat/historial",
        headers={"Authorization": f"Bearer {sesion.json()['token']}"},
    )

    contenidos = [i["contenido"] for i in historial.json()["interacciones"]]
    assert contenidos == ["Su reclamo está en revisión."]


async def test_nota_interna_se_permite_con_caso_cerrado(client, auth_headers, ciudadano):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "web"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]
    await client.patch(
        f"/api/casos/{caso_id}/estado",
        json={"estado": "cerrado", "motivo": "resuelto"},
        headers=auth_headers,
    )

    nota = await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Cerrado por duplicado del caso anterior.", "interna": True},
        headers=auth_headers,
    )
    respuesta = await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Hola de nuevo"},
        headers=auth_headers,
    )

    assert nota.status_code == 201
    assert respuesta.status_code == 422


async def test_cerrar_sin_motivo_devuelve_422(client, auth_headers, ciudadano):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "web"},
        headers=auth_headers,
    )

    response = await client.patch(
        f"/api/casos/{creado.json()['id']}/estado",
        json={"estado": "cerrado"},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_cerrar_con_motivo_lo_persiste_y_audita(client, auth_headers, ciudadano):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "web"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    response = await client.patch(
        f"/api/casos/{caso_id}/estado",
        json={"estado": "cerrado", "motivo": "duplicado"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["motivo_cierre"] == "duplicado"

    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    cierres = [e for e in auditoria.json() if e["accion"] == "cambio_estado"]
    assert cierres[-1]["metadata"]["motivo"] == "duplicado"


# --- Ciclo de vida del estado ----------------------------------------------


async def test_el_ciclo_completo_de_estados(
    client, auth_headers, usuario_admin, ciudadano
):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "email"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    tomado = await client.patch(
        f"/api/casos/{caso_id}/asignacion",
        json={"operador_asignado_id": str(usuario_admin.id)},
        headers=auth_headers,
    )
    assert tomado.json()["estado"] == "en_progreso"

    liberado = await client.patch(
        f"/api/casos/{caso_id}/asignacion",
        json={"operador_asignado_id": None},
        headers=auth_headers,
    )
    assert liberado.json()["estado"] == "abierto"


async def test_un_caso_cerrado_no_cambia_de_estado_al_asignarlo(
    client, auth_headers, usuario_admin, ciudadano
):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "email"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]
    await client.patch(
        f"/api/casos/{caso_id}/estado",
        json={"estado": "cerrado", "motivo": "resuelto"},
        headers=auth_headers,
    )

    asignado = await client.patch(
        f"/api/casos/{caso_id}/asignacion",
        json={"operador_asignado_id": str(usuario_admin.id)},
        headers=auth_headers,
    )

    assert asignado.json()["estado"] == "cerrado"
