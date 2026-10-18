"""El ciudadano tiene que saber que le contesta una IA.

Se antepone por código y no se le pide al modelo: un aviso de transparencia que
depende de que el LLM se acuerde de decirlo no es un aviso, es una intención.
"""

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.aviso_ia import AVISO_IA
from app.agents.graph import procesar_mensaje
from app.agents.saludo import RESPUESTA_SALUDO
from app.core.config import settings
from app.db.models import ActorInteraccion, Canal, Caso, Interaccion
from app.schemas.agente import ClasificacionIntent


@pytest.fixture
def vigencia_del_aviso(mocker):
    """Fija la vigencia: el valor del `.env` de la máquina no decide el test."""
    mocker.patch.object(settings, "agente_horas_aviso_ia", 12)
    return 12


def test_el_saludo_avisa_que_es_una_ia():
    """El saludo no abre caso, así que lleva el aviso en su propio texto."""
    texto = RESPUESTA_SALUDO.lower()
    assert "inteligencia artificial" in texto
    assert "asistente virtual" in texto


async def test_el_primer_mensaje_del_caso_lleva_el_aviso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14.")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"].startswith(AVISO_IA)
    assert final["respuesta"].endswith("Atendemos de 8 a 14.")


async def test_el_aviso_no_se_repite_en_cada_respuesta(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """Repetirlo en cada mensaje convierte la conversación en un formulario."""
    mock_llms(
        [
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        ],
        respuestas_ejecutor=[
            AIMessage(content="Atendemos de 8 a 14."),
            AIMessage(content="En Avenida Siempreviva 742."),
        ],
    )

    primero = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )
    segundo = await procesar_mensaje(
        db_session,
        mensaje="¿Y dónde quedan?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert primero["respuesta"].startswith(AVISO_IA)
    assert AVISO_IA not in segundo["respuesta"]


async def test_el_aviso_queda_en_lo_que_se_persiste_y_no_solo_en_lo_que_se_manda(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El operador tiene que ver en el caso exactamente lo que leyó el ciudadano."""
    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14.")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    guardada = (
        (
            await db_session.execute(
                select(Interaccion).where(
                    Interaccion.actor == ActorInteraccion.agente_ia,
                )
            )
        )
        .scalars()
        .first()
    )
    assert guardada.contenido == final["respuesta"]
    assert guardada.contenido.startswith(AVISO_IA)


async def test_el_aviso_no_se_repite_aunque_cada_mensaje_abra_un_caso_nuevo(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, vigencia_del_aviso
):
    """El bug reportado: por WhatsApp el ciudadano cambia de tema y el intake
    abre un caso por mensaje. Con el aviso atado al caso salía en todos, que es
    justo lo que no queremos."""
    mock_llms(
        [
            ClasificacionIntent(
                intencion="consulta", entidades={}, confianza=0.95,
                continua_caso_abierto=False,
            ),
            ClasificacionIntent(
                intencion="reclamo", entidades={}, confianza=0.95,
                continua_caso_abierto=False,
            ),
        ],
        respuestas_ejecutor=[
            AIMessage(content="Puedo tomar reclamos y reservar turnos."),
            AIMessage(content="Tomé nota del perro perdido en Santa Fe al 100."),
        ],
    )

    primero = await procesar_mensaje(
        db_session,
        mensaje="¿De qué trámites tenés conocimiento?",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )
    segundo = await procesar_mensaje(
        db_session,
        mensaje="Quería reportar que hay un perro perdido en Santa Fe al 100",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert primero["caso_id"] != segundo["caso_id"], "cada mensaje abrió su caso"
    assert primero["respuesta"].startswith(AVISO_IA)
    assert AVISO_IA not in segundo["respuesta"], "el aviso no se repite en la misma charla"

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 2


async def test_vuelve_a_avisar_cuando_pasaron_horas_sin_hablar(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, vigencia_del_aviso
):
    """Si el ciudadano vuelve al día siguiente ya no tiene presente con qué
    estaba hablando: el recordatorio vuelve a tener sentido."""
    from datetime import datetime, timedelta, timezone

    from app.db.models import EstadoCaso, TipoCaso

    viejo = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.cerrado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(viejo)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=viejo.id,
            contenido="Atendemos de 8 a 14.",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.agente_ia,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=30),
        )
    )
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.95),
        respuestas_ejecutor=[AIMessage(content="Estamos en Avenida Siempreviva 742.")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Dónde quedan?",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"].startswith(AVISO_IA)


async def test_el_aviso_es_por_canal(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, vigencia_del_aviso
):
    """Avisarle por WhatsApp no le sirve al que después abre el correo."""
    mock_llms(
        [
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.95),
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.95),
        ],
        respuestas_ejecutor=[
            AIMessage(content="Atendemos de 8 a 14."),
            AIMessage(content="Atendemos de 8 a 14."),
        ],
    )

    por_whatsapp = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen?",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )
    por_correo = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert por_whatsapp["respuesta"].startswith(AVISO_IA)
    assert por_correo["respuesta"].startswith(AVISO_IA)
