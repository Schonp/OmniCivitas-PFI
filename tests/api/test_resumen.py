"""Resumen del caso generado por IA a pedido del operador."""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage

from app.db.models import ActorInteraccion, Canal, Interaccion


def _mock_llm_resumen(mocker, texto: str = "La ciudadana reclama por una luminaria rota."):
    mock = MagicMock()
    mock.ainvoke = AsyncMock(return_value=AIMessage(content=texto))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=mock)
    return mock


async def _crear_caso(client, auth_headers, ciudadano) -> str:
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "whatsapp"},
        headers=auth_headers,
    )
    return creado.json()["id"]


async def test_generar_resumen_lo_persiste_y_audita(
    client, db_session, auth_headers, ciudadano, mocker
):
    _mock_llm_resumen(mocker)
    caso_id = await _crear_caso(client, auth_headers, ciudadano)
    db_session.add(
        Interaccion(
            caso_id=caso_id,
            contenido="Se rompió la luminaria de mi cuadra.",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
        )
    )
    await db_session.commit()

    response = await client.post(f"/api/casos/{caso_id}/resumen", headers=auth_headers)

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["resumen_ia"] == "La ciudadana reclama por una luminaria rota."
    assert cuerpo["resumen_ia_generado_en"] is not None

    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    acciones = [registro["accion"] for registro in auditoria.json()]
    assert "resumen_ia" in acciones


async def test_generar_resumen_sin_interacciones_devuelve_422(
    client, auth_headers, ciudadano, mocker
):
    llm = _mock_llm_resumen(mocker)
    caso_id = await _crear_caso(client, auth_headers, ciudadano)

    response = await client.post(f"/api/casos/{caso_id}/resumen", headers=auth_headers)

    assert response.status_code == 422
    llm.ainvoke.assert_not_awaited()


async def test_resumen_excluye_notas_internas_del_contexto(
    client, db_session, auth_headers, ciudadano, mocker
):
    llm = _mock_llm_resumen(mocker)
    caso_id = await _crear_caso(client, auth_headers, ciudadano)
    db_session.add(
        Interaccion(
            caso_id=caso_id,
            contenido="Reclamo por bache en la calle.",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
        )
    )
    await db_session.commit()
    await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Nota interna: vecino conflictivo.", "interna": True},
        headers=auth_headers,
    )

    await client.post(f"/api/casos/{caso_id}/resumen", headers=auth_headers)

    prompt = llm.ainvoke.await_args.args[0]
    texto_prompt = "".join(str(mensaje.content) for mensaje in prompt)
    assert "Reclamo por bache" in texto_prompt
    assert "vecino conflictivo" not in texto_prompt


async def test_resumen_con_llm_caido_devuelve_502(
    client, db_session, auth_headers, ciudadano, mocker
):
    mock = MagicMock()
    mock.ainvoke = AsyncMock(side_effect=RuntimeError("api caida"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=mock)
    caso_id = await _crear_caso(client, auth_headers, ciudadano)
    db_session.add(
        Interaccion(
            caso_id=caso_id,
            contenido="¿Cómo renuevo mi licencia?",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
        )
    )
    await db_session.commit()

    response = await client.post(f"/api/casos/{caso_id}/resumen", headers=auth_headers)

    assert response.status_code == 502
