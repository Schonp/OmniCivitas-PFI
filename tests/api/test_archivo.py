"""Un caso cerrado se archiva: sale de la bandeja activa y solo aparece
pidiendo la solapa "archivados"."""

from app.db.models import Canal, Caso, Ciudadano, EstadoCaso, TipoCaso


async def _caso(db_session, nombre: str, documento: str, estado: EstadoCaso) -> Caso:
    persona = Ciudadano(documento=documento, nombre=nombre, email=f"{documento}@test.com")
    db_session.add(persona)
    await db_session.flush()

    caso = Caso(
        ciudadano_id=persona.id, tipo=TipoCaso.consulta, estado=estado,
        canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.commit()
    return caso


async def test_un_cerrado_no_aparece_en_la_bandeja_por_defecto(client, db_session, auth_headers):
    activo = await _caso(db_session, "Activo", "60111111", EstadoCaso.abierto)
    await _caso(db_session, "Cerrado", "60222222", EstadoCaso.cerrado)

    respuesta = await client.get("/api/casos", headers=auth_headers)

    referencias = [c["id"] for c in respuesta.json()]
    assert referencias == [str(activo.id)]


async def test_el_filtro_todos_de_la_bandeja_activa_tampoco_trae_cerrados(
    client, db_session, auth_headers
):
    """"Todos" dentro de la bandeja significa "todos los activos", no
    literalmente todos: el cerrado ya vive en su propia solapa."""
    activo = await _caso(db_session, "Activo", "60333333", EstadoCaso.escalado)
    await _caso(db_session, "Cerrado", "60444444", EstadoCaso.cerrado)

    # "Todos" en la bandeja activa es no mandar `estado`: así es como lo pide
    # el frontend para ese chip.
    respuesta = await client.get("/api/casos", headers=auth_headers)

    ids = [c["id"] for c in respuesta.json()]
    assert str(activo.id) in ids
    assert not any(c["estado"] == "cerrado" for c in respuesta.json())


async def test_la_solapa_archivados_muestra_solo_cerrados(client, db_session, auth_headers):
    await _caso(db_session, "Activo", "60555555", EstadoCaso.abierto)
    cerrado = await _caso(db_session, "Cerrado", "60666666", EstadoCaso.cerrado)

    respuesta = await client.get(
        "/api/casos", params={"archivados": "true"}, headers=auth_headers
    )

    ids = [c["id"] for c in respuesta.json()]
    assert ids == [str(cerrado.id)]


async def test_archivados_ignora_el_chip_de_estado(client, db_session, auth_headers):
    """La solapa archivados no ofrece chips de estado en la UI, pero si de
    todos modos llegara uno, no tiene que devolver una lista vacía por el
    choque entre archivados=true y estado=abierto."""
    cerrado = await _caso(db_session, "Cerrado", "60777777", EstadoCaso.cerrado)

    respuesta = await client.get(
        "/api/casos",
        params={"archivados": "true", "estado": "abierto"},
        headers=auth_headers,
    )

    assert [c["id"] for c in respuesta.json()] == [str(cerrado.id)]


async def test_conteos_todos_no_incluye_los_cerrados(client, db_session, auth_headers):
    await _caso(db_session, "Uno", "60888881", EstadoCaso.abierto)
    await _caso(db_session, "Dos", "60888882", EstadoCaso.en_progreso)
    await _caso(db_session, "Tres", "60888883", EstadoCaso.cerrado)
    await _caso(db_session, "Cuatro", "60888884", EstadoCaso.cerrado)

    cuerpo = (await client.get("/api/casos/conteos", headers=auth_headers)).json()

    assert cuerpo["todos"] == 2
    assert cuerpo["por_estado"]["cerrado"] == 2, "el conteo de archivados sigue disponible"


async def test_exportar_sigue_incluyendo_cerrados(client, db_session, auth_headers):
    """El CSV es para reportes del organismo: no tiene que perder el
    historial resuelto solo porque la bandeja lo archivó."""
    await _caso(db_session, "Activo", "60999991", EstadoCaso.abierto)
    await _caso(db_session, "Cerrado", "60999992", EstadoCaso.cerrado)

    respuesta = await client.get("/api/casos/exportar", headers=auth_headers)

    cuerpo = respuesta.content.decode("utf-8-sig")
    assert "60999991" in cuerpo
    assert "60999992" in cuerpo
