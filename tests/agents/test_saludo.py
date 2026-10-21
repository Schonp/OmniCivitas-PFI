"""Un saludo se contesta, no se escala ni abre caso.

Toda conversación arranca con un "hola". Antes caía en la intención "otro", que
el router manda a escalado, así que cada persona que saludaba terminaba en la
bandeja de un operador y su saludo se pegaba al último caso abierto que tuviera,
aunque fuera de otro tema y otro canal.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.graph import decidir_ruta, procesar_mensaje
from app.agents.saludo import RESPUESTA_SALUDO, armar_saludo
from app.db.models import Canal, Caso, EstadoCaso, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent


def test_el_saludo_por_voz_no_tiene_menu_numerado():
    """Un menú de 3 opciones se lee bien pero se escucha como un formulario:
    por voz se abre con una pregunta, no con una lista (ver DEVLOG.md de
    voz_asr_tts, "Diferenciar voz de texto")."""
    saludo = armar_saludo([], canal=Canal.voz)

    assert "1." not in saludo
    assert "2." not in saludo
    assert saludo != RESPUESTA_SALUDO


def test_el_saludo_por_whatsapp_mantiene_el_menu():
    saludo = armar_saludo([], canal=Canal.whatsapp)

    assert saludo == RESPUESTA_SALUDO


def _estado(intencion: str, **extra):
    base = {
        "intencion": intencion,
        "confianza": 0.95,
        "requiere_escalado": False,
        "identificado": True,
        "caso_id": str(uuid.uuid4()),
    }
    return {**base, **extra}


def test_un_saludo_no_va_a_escalado():
    assert decidir_ruta(_estado("saludo")) == "saludo"


def test_el_saludo_gana_aunque_la_confianza_sea_baja():
    """La confianza baja manda a escalado; un saludo no tiene por qué tenerla
    alta y aun así no justifica molestar a un operador."""
    assert decidir_ruta(_estado("saludo", confianza=0.1)) == "saludo"


@pytest.mark.parametrize("intencion", ["reclamo", "consulta", "tramite"])
def test_las_demas_intenciones_no_se_desvian(intencion):
    assert decidir_ruta(_estado(intencion)) != "saludo"


async def test_saludar_no_abre_caso_ni_deja_interacciones(
    db_session, mock_llms, checkpointer_en_memoria, ciudadano
):
    mock_llms(
        ClasificacionIntent(
            intencion="saludo", entidades={}, confianza=0.9, continua_caso_abierto=False
        ),
        respuestas_ejecutor=[],
    )

    final = await procesar_mensaje(
        db_session, mensaje="Hola", canal=Canal.whatsapp, identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"] == RESPUESTA_SALUDO
    assert final["caso_id"] is None
    assert final.get("requiere_escalado") is not True

    casos = (await db_session.execute(select(Caso))).scalars().all()
    assert casos == [], "un saludo no es una unidad de gestión"


async def test_el_saludo_no_se_pega_a_un_caso_abierto_de_otro_tema(
    db_session, mock_llms, checkpointer_en_memoria, ciudadano
):
    """El bug reportado: un "Hola" por WhatsApp se enganchó a una consulta que
    venía por email, y quedó escalada."""
    ajeno = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.abierto,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
        asunto="Número de habitantes del municipio",
    )
    db_session.add(ajeno)
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(
            intencion="saludo", entidades={}, confianza=0.9, continua_caso_abierto=False
        ),
        respuestas_ejecutor=[],
    )

    final = await procesar_mensaje(
        db_session, mensaje="Hola?", canal=Canal.whatsapp, identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["caso_id"] is None
    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == ajeno.id)))
        .scalars()
        .all()
    )
    assert interacciones == [], "el saludo no debe tocar el caso de email"

    await db_session.refresh(ajeno)
    assert ajeno.estado == EstadoCaso.abierto, "saludar no escala el caso ajeno"
