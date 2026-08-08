import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.agents.escalado import RESPUESTA_ESCALADO
from app.agents.graph import procesar_mensaje
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


def _mock_llms(mocker, clasificacion: ClasificacionIntent, respuestas_ejecutor=None):
    mock_intake = MagicMock()
    mock_intake.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=clasificacion
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
            db_session, mensaje="hola", canal=Canal.web, identificador="juan.perez@test.com"
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

    assert final["respuesta"] == "Su reclamo fue registrado. Le informaremos las novedades."
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


async def test_grafo_escala_con_confianza_baja(db_session, ciudadano, mocker):
    _mock_llms(
        mocker,
        ClasificacionIntent(intencion="otro", entidades={}, confianza=0.3),
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="ehh no sé, es un tema medio raro",
        canal=Canal.whatsapp,
        identificador="+5491122334455",
        checkpointer=InMemorySaver(),
    )

    assert final["requiere_escalado"] is True
    assert final["respuesta"] == RESPUESTA_ESCALADO

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.estado == EstadoCaso.escalado

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    escalados = [a for a in auditorias if a.accion == "escalado"]
    assert escalados and escalados[0].metadata_["resumen"] == "Resumen para operador"
