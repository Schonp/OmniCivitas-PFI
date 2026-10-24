import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.agents.escalado import CIERRE_ESCALADO, MOTIVO_EN_CRIOLLO
from app.agents.graph import procesar_mensaje
from app.agents.opciones import RESPUESTA_OPCIONES
from app.db.models import (
    ActorInteraccion,
    Auditoria,
    Canal,
    Caso,
    EstadoCaso,
    Interaccion,
    TipoCaso,
)
from app.schemas.agente import ClasificacionIntent


def _mock_llms(mocker, clasificacion, respuestas_ejecutor=None):
    """`clasificacion` acepta una lista para cubrir varios mensajes seguidos."""
    if isinstance(clasificacion, ClasificacionIntent):
        clasificacion = [clasificacion]
    mock_intake = MagicMock()
    mock_intake.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=list(clasificacion)
    )
    # El nodo escalado usa el mismo LLM barato para el resumen del operador.
    mock_intake.ainvoke = AsyncMock(return_value=AIMessage(content="Resumen para operador"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=mock_intake)

    mock_ejecutor = MagicMock()
    if respuestas_ejecutor is not None:
        mock_ejecutor.bind_tools.return_value.ainvoke = AsyncMock(
            side_effect=respuestas_ejecutor
        )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=mock_ejecutor)


async def test_procesar_mensaje_sin_checkpointer_inicializado_falla(db_session, ciudadano):
    """Sin checkpointer el orquestador corta con un error explícito: antes hacía
    el setup dentro del request y se bloqueaba contra su propia transacción."""
    with pytest.raises(RuntimeError, match="checkpointer"):
        await procesar_mensaje(
            db_session, mensaje="hola", canal=Canal.email, identificador="juan.perez@test.com"
        )


async def test_grafo_end_to_end_crea_reclamo(db_session, ciudadano, mocker):
    _mock_llms(
        mocker,
        ClasificacionIntent(
            intencion="reclamo", entidades={"categoria": "infraestructura"}, confianza=0.9
        ),
        respuestas_ejecutor=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reclamo",
                        "args": {
                            "descripcion": "La vereda está rota",
                            "categoria": "infraestructura",
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Su reclamo fue registrado. Le informaremos las novedades."),
        ],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="La vereda de mi barrio está rota",
        canal=Canal.whatsapp,
        identificador="+5491122334455",
        checkpointer=InMemorySaver(),
    )

    # La confirmación sale de los datos reales del reclamo, no de una segunda
    # vuelta del modelo (ver app/agents/confirmacion.py).
    assert "Registré su reclamo por la vereda está rota." in final["respuesta"]
    assert final["requiere_escalado"] is False

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo
    assert caso.ciudadano_id == ciudadano.id

    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    actores = {i.actor for i in interacciones}
    assert ActorInteraccion.ciudadano in actores
    assert ActorInteraccion.agente_ia in actores

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    acciones = {a.accion for a in auditorias}
    assert "creacion_reclamo" in acciones
    assert "respuesta_ia" in acciones


async def test_grafo_escala_cuando_se_agotan_las_repreguntas(db_session, ciudadano, mocker):
    """Un mensaje que no se entiende ya no deriva de una: primero se pregunta.
    Recién agotadas las vueltas interviene una persona."""
    _mock_llms(
        mocker,
        [ClasificacionIntent(intencion="otro", entidades={}, confianza=0.3)] * 3,
    )
    saver = InMemorySaver()

    async def _mandar(texto: str):
        return await procesar_mensaje(
            db_session,
            mensaje=texto,
            canal=Canal.whatsapp,
            identificador="+5491122334455",
            checkpointer=saver,
        )

    primera = await _mandar("ehh no sé, es un tema medio raro")
    assert primera["caso_id"] is None, "sin saber de qué se trata no se abre caso"
    assert RESPUESTA_OPCIONES in primera["respuesta"]

    segunda = await _mandar("no sé cómo explicarlo")
    assert segunda["caso_id"] is None
    assert RESPUESTA_OPCIONES in segunda["respuesta"]

    final = await _mandar("es complicado")

    assert final["requiere_escalado"] is True

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    # El aviso explica el motivo y deja la referencia: sin ella el ciudadano no
    # tiene con qué reclamar después.
    assert MOTIVO_EN_CRIOLLO["confianza_baja"] in final["respuesta"]
    assert caso.referencia in final["respuesta"]
    assert CIERRE_ESCALADO in final["respuesta"]
    assert caso.estado == EstadoCaso.escalado

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    escalados = [a for a in auditorias if a.accion == "escalado"]
    assert escalados and escalados[0].metadata_["resumen"] == "Resumen para operador"


async def test_si_el_modelo_falla_el_caso_se_deriva_y_el_ciudadano_recibe_respuesta(
    db_session, ciudadano, mocker
):
    """RNF-03: con el servidor del modelo caído, la excepción subía hasta el
    webhook y el mensaje del ciudadano se perdía sin respuesta."""
    caido = MagicMock()
    caido.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=RuntimeError("llama-server process has terminated")
    )
    caido.ainvoke = AsyncMock(side_effect=RuntimeError("llama-server process has terminated"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=caido)
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=caido)

    final = await procesar_mensaje(
        db_session,
        mensaje="Hay un pozo en Thames 1200",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=InMemorySaver(),
    )

    assert MOTIVO_EN_CRIOLLO["falla_tecnica"] in final["respuesta"]
    assert final["requiere_escalado"] is True
    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.estado in (EstadoCaso.escalado, EstadoCaso.en_progreso)
    # Sin el resumen del modelo, el operador recibe el mensaje original.
    assert caso.resumen_ia == "Hay un pozo en Thames 1200"
    motivos = (
        await db_session.execute(
            select(Auditoria.metadata_).where(Auditoria.caso_id == caso.id, Auditoria.accion == "escalado")
        )
    ).scalars().all()
    assert motivos and motivos[0]["motivo"] == "falla_tecnica"
