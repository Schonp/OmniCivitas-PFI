import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.graph import procesar_mensaje
from app.agents.titulos import titulo_automatico
from app.db.models import Canal, Caso, TipoCaso
from app.schemas.agente import ClasificacionIntent


@pytest.mark.parametrize(
    "tipo,mensaje,esperado",
    [
        (TipoCaso.consulta, "Hola, ¿qué horario tiene el centro de salud?", "Qué horario tiene el centro de salud"),
        (TipoCaso.tramite, "Buenos días! Quiero habilitar un local", "Quiero habilitar un local"),
        (TipoCaso.consulta, "3", None),
        (TipoCaso.consulta, "Sí", None),
        (TipoCaso.consulta, None, None),
    ],
)
def test_titulo_automatico(tipo, mensaje, esperado):
    assert titulo_automatico(tipo, mensaje) == esperado


def test_un_mensaje_largo_se_corta_en_una_palabra_entera():
    titulo = titulo_automatico(TipoCaso.consulta, "quiero saber " + "cuáles son los requisitos " * 6)

    assert len(titulo) <= 70
    assert not titulo.endswith(("requi", "cuá"))


async def test_la_consulta_se_abre_con_titulo(db_session, ciudadano, mock_llms, checkpointer_en_memoria):
    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14.")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Qué horario tienen los fines de semana?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    caso = (await db_session.execute(select(Caso).where(Caso.id == __import__("uuid").UUID(final["caso_id"])))).scalar_one()
    assert caso.titulo == "Qué horario tienen los fines de semana"


async def test_el_caso_derivado_queda_con_titulo(db_session, ciudadano, mock_llms, checkpointer_en_memoria):
    mock_llms(ClasificacionIntent(intencion="tramite", entidades={}, confianza=0.9))

    final = await procesar_mensaje(
        db_session,
        mensaje="Necesito habilitar un comercio de comidas",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final.get("requiere_escalado")
    caso = (await db_session.execute(select(Caso))).scalars().first()
    assert caso.titulo == "Necesito habilitar un comercio de comidas"
