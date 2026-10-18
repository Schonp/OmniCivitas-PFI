"""Responder con un número tiene que funcionar de verdad.

El menú invita a contestar "1" o "4", y eso no se le puede preguntar al modelo:
el saludo que mostró la lista no abre caso, así que no queda en el historial y
el clasificador recibiría un número pelado, sin nada con qué interpretarlo.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.eleccion import armar_ofertas, es_eleccion, resolver
from app.agents.graph import procesar_mensaje
from app.db.models import Canal, Caso, EstadoCaso, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent

SALUDO = ClasificacionIntent(
    intencion="saludo", entidades={}, confianza=0.98, continua_caso_abierto=False
)


def _caso(ciudadano_id) -> Caso:
    return Caso(
        id=uuid.uuid4(),
        ciudadano_id=ciudadano_id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )


def test_los_casos_se_numeran_despues_del_menu():
    """Con dos listas que arrancan en 1, un "2" sería ambiguo."""
    casos = [_caso(uuid.uuid4()), _caso(uuid.uuid4())]

    ofertas = armar_ofertas(casos)

    assert [o["numero"] for o in ofertas] == [1, 2, 3, 4, 5]
    assert ofertas[0]["intencion"] == "reclamo"
    assert ofertas[3]["caso_id"] == str(casos[0].id)


@pytest.mark.parametrize("texto", ["4", " 4 ", "4.", "4)", "el 4", "opción 4", "#4", "Caso 4"])
def test_formas_de_elegir_que_valen(texto):
    ofertas = armar_ofertas([_caso(uuid.uuid4())])
    assert resolver(texto, ofertas) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Necesito un turno el 4 de octubre",
        "hay 4 pozos en la cuadra",
        "quiero un reclamo",
        "",
    ],
)
def test_lo_que_no_es_una_eleccion(texto):
    """Un número adentro de una frase no es elegir del menú."""
    ofertas = armar_ofertas([_caso(uuid.uuid4())])
    assert resolver(texto, ofertas) is None
    assert not es_eleccion(texto)


def test_un_numero_fuera_de_la_lista_no_resuelve():
    ofertas = armar_ofertas([])  # solo 1, 2 y 3
    assert resolver("7", ofertas) is None


async def test_elegir_el_numero_de_un_caso_lo_retoma(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    caso = _caso(ciudadano.id)
    db_session.add(caso)
    await db_session.commit()

    # Solo se mockea la clasificación del saludo: el "4" se resuelve por código,
    # sin llamar al modelo.
    mock_llms(SALUDO)

    saludo = await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )
    assert "4." in saludo["respuesta"]

    eleccion = await procesar_mensaje(
        db_session,
        mensaje="4",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert eleccion["caso_id"] == str(caso.id)


async def test_elegir_un_tipo_del_menu_no_pasa_por_el_modelo(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """Si el "1" fuera al clasificador, llegaría sin el menú delante."""
    from langchain_core.messages import AIMessage

    mock_llms(SALUDO, respuestas_ejecutor=[AIMessage(content="Cuénteme qué pasó.")])

    await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    # El mock de clasificación tiene una sola respuesta cargada: si el "1"
    # llamara al modelo, este ainvoke reventaría por StopIteration.
    eleccion = await procesar_mensaje(
        db_session,
        mensaje="1",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    caso = await db_session.get(Caso, uuid.UUID(eleccion["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo


async def test_las_ofertas_se_consumen(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """Un número suelto de mañana no puede caer en la lista de hoy."""
    caso = _caso(ciudadano.id)
    db_session.add(caso)
    await db_session.commit()

    mock_llms(
        [
            SALUDO,
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        ]
    )

    await procesar_mensaje(
        db_session, mensaje="Hola", canal=Canal.whatsapp,
        identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
    )
    await procesar_mensaje(
        db_session, mensaje="4", canal=Canal.whatsapp,
        identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
    )

    # El segundo "4" ya no tiene lista contra la cual resolverse: vuelve a pasar
    # por el clasificador, que es lo que consume la segunda clasificación.
    segundo = await procesar_mensaje(
        db_session, mensaje="4", canal=Canal.whatsapp,
        identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
    )
    assert segundo["intencion"] == "consulta"


async def test_elegir_tramite_no_genera_un_resumen_alucinado(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El bug real: el resumen para el operador se armaba pidiéndole al LLM
    que resuma el mensaje "3", y sin nada que resumir terminó contestándole
    al ciudadano en vez de resumirle al operador. Con origen_menu no hace
    falta LLM: se sabe exactamente qué pasó."""
    mock_llms(SALUDO)

    await procesar_mensaje(
        db_session, mensaje="Hola", canal=Canal.whatsapp,
        identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
    )
    final = await procesar_mensaje(
        db_session, mensaje="3", canal=Canal.whatsapp,
        identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
    )

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.estado == EstadoCaso.escalado
    assert caso.resumen_ia == 'Eligió "Trámite" en el menú de inicio, sin dar más detalle todavía.'


async def test_elegir_reclamo_le_avisa_al_ejecutor_que_no_hay_descripcion(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El bug real: el ejecutor recibía el "1" pelado, sin saber que era una
    elección del menú, y o volvía a saludar o preguntaba qué quiso decir con
    "1". Se verifica que el system prompt que arma el ejecutor incluye el
    aviso del origen, no la respuesta del LLM (que ya está mockeada)."""
    from unittest.mock import AsyncMock, MagicMock

    from langchain_core.messages import AIMessage

    mensajes_capturados = []

    mock_ejecutor = MagicMock()

    async def _capturar(mensajes):
        mensajes_capturados.extend(mensajes)
        return AIMessage(content="¿De qué se trata el reclamo?")

    mock_ejecutor.bind_tools.return_value.ainvoke = AsyncMock(side_effect=_capturar)

    from unittest.mock import patch

    mock_llms(SALUDO)
    with patch("app.agents.llm.get_llm_ejecutor", return_value=mock_ejecutor):
        await procesar_mensaje(
            db_session, mensaje="Hola", canal=Canal.whatsapp,
            identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
        )
        await procesar_mensaje(
            db_session, mensaje="1", canal=Canal.whatsapp,
            identificador=ciudadano.telefono, checkpointer=checkpointer_en_memoria,
        )

    system = mensajes_capturados[0].content
    assert 'acaba de elegir "reclamo" en el menú de inicio' in system.lower()

    # Lo que se persiste sigue siendo lo que el ciudadano tipeó de verdad.
    guardado = (
        (
            await db_session.execute(
                select(Interaccion).where(Interaccion.contenido == "1")
            )
        )
        .scalars()
        .first()
    )
    assert guardado is not None, "el mensaje real ('1') no se reescribe en la auditoría"
