"""Un reclamo o una reserva que arranca incompleto no se parte en dos casos.

El bug real: `_abrir_caso` (graph.py) abre el caso apenas se detecta la
intención, aunque falte un dato para poder ejecutar la tool (la dirección de
un reclamo, el día de un turno). Cuando el ciudadano por fin lo da, la tool
`crear_reclamo`/`crear_reserva` ignoraba ese caso y abría uno nuevo: el mensaje
final quedaba en un caso aparte, sin el resto de la conversación.
"""

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.graph import procesar_mensaje
from app.db.models import Canal, Caso, Interaccion, TipoCaso, Turno
from app.schemas.agente import ClasificacionIntent
from tests.horarios import horario


async def test_el_reclamo_que_arranca_sin_direccion_no_se_parte_en_dos_casos(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms(
        [ClasificacionIntent(intencion="reclamo", entidades={}, confianza=0.95)] * 2,
        respuestas_ejecutor=[
            # Primer turno: sin datos para ejecutar, el ejecutor pregunta.
            AIMessage(content="¿En qué dirección está el árbol caído?"),
            # Segundo turno: con la dirección, recién ahí llama a la tool.
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reclamo",
                        "args": {
                            "descripcion": "Árbol caído en Anchorena 2459",
                            "categoria": "infraestructura",
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Su reclamo quedó registrado."),
        ],
    )

    primero = await procesar_mensaje(
        db_session,
        mensaje="Se cayó un árbol en mi calle",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )
    segundo = await procesar_mensaje(
        db_session,
        mensaje="Anchorena 2459",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert primero["caso_id"] == segundo["caso_id"]

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1
    assert casos[0].tipo == TipoCaso.reclamo

    contenidos = {
        i.contenido
        for i in (
            await db_session.execute(
                select(Interaccion).where(Interaccion.caso_id == casos[0].id)
            )
        )
        .scalars()
        .all()
    }
    assert "Se cayó un árbol en mi calle" in contenidos
    assert "Anchorena 2459" in contenidos


async def test_la_reserva_que_arranca_sin_horario_no_se_parte_en_dos_casos(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    db_session.add(Turno(nombre="Renovación de DNI", descripcion="Sede comunal."))
    await db_session.commit()

    mock_llms(
        [ClasificacionIntent(intencion="reserva", entidades={}, confianza=0.95)] * 2,
        respuestas_ejecutor=[
            AIMessage(content="¿Qué día y horario le queda cómodo?"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reserva",
                        "args": {
                            "turno": "Renovación de DNI",
                            "fecha_hora": horario(hora="13:00"),
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Su turno quedó reservado."),
        ],
    )

    primero = await procesar_mensaje(
        db_session,
        mensaje="Quiero renovar el DNI",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )
    segundo = await procesar_mensaje(
        db_session,
        mensaje="El 17/9 a las 13",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert primero["caso_id"] == segundo["caso_id"]

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1
    assert casos[0].tipo == TipoCaso.reserva
