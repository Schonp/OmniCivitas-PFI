"""Reclamos en común agrupados por IA (vista del supervisor)."""

from unittest.mock import AsyncMock, MagicMock

from app.agents.agrupador import AgrupacionReclamos, GrupoDetectado
from app.db.models import ActorInteraccion, Canal, Caso, Ciudadano, Interaccion, TipoCaso


async def _reclamo(db_session, nombre: str, documento: str, contenido: str) -> Caso:
    persona = Ciudadano(documento=documento, nombre=nombre, email=f"{documento}@test.com")
    db_session.add(persona)
    await db_session.flush()

    caso = Caso(
        ciudadano_id=persona.id,
        tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido=contenido,
            canal=Canal.whatsapp,
            actor=ActorInteraccion.ciudadano,
        )
    )
    return caso


def _mock_llm_agrupador(mocker, agrupacion: AgrupacionReclamos):
    mock = MagicMock()
    mock.with_structured_output.return_value.ainvoke = AsyncMock(return_value=agrupacion)
    mocker.patch("app.agents.llm.get_llm_intake", return_value=mock)


async def test_generar_grupos_persiste_y_descarta_ids_inventados(
    client, db_session, auth_headers, mocker
):
    uno = await _reclamo(db_session, "Vecina A", "80111222", "No pasa el camión de basura.")
    dos = await _reclamo(db_session, "Vecino B", "80333444", "La basura sigue en la esquina.")
    await db_session.commit()

    _mock_llm_agrupador(
        mocker,
        AgrupacionReclamos(
            grupos=[
                GrupoDetectado(
                    tema="Falta de recolección",
                    caso_ids=[str(uno.id), str(dos.id), "00000000-0000-0000-0000-000000000000"],
                )
            ]
        ),
    )

    generado = await client.post("/api/reclamos/grupos/generar", headers=auth_headers)

    assert generado.status_code == 200
    grupos = generado.json()
    assert len(grupos) == 1
    assert grupos[0]["tema"] == "Falta de recolección"
    assert {c["id"] for c in grupos[0]["casos"]} == {str(uno.id), str(dos.id)}

    persistido = await client.get("/api/reclamos/grupos", headers=auth_headers)
    assert [g["tema"] for g in persistido.json()] == ["Falta de recolección"]


async def test_grupo_de_un_solo_reclamo_se_descarta(client, db_session, auth_headers, mocker):
    solo = await _reclamo(db_session, "Vecina C", "80555666", "Ruidos molestos de un bar.")
    await _reclamo(db_session, "Vecino D", "80777888", "Vereda rota en mi cuadra.")
    await db_session.commit()

    _mock_llm_agrupador(
        mocker,
        AgrupacionReclamos(grupos=[GrupoDetectado(tema="Ruidos", caso_ids=[str(solo.id)])]),
    )

    generado = await client.post("/api/reclamos/grupos/generar", headers=auth_headers)

    assert generado.status_code == 200
    assert generado.json() == []


async def test_grupos_son_solo_del_supervisor(client, headers_operador):
    lectura = await client.get("/api/reclamos/grupos", headers=headers_operador)
    generacion = await client.post("/api/reclamos/grupos/generar", headers=headers_operador)

    assert lectura.status_code == 403
    assert generacion.status_code == 403
