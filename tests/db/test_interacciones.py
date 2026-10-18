"""`primeros_mensajes_de_casos`: qué mensaje representa cada caso.

Se salta la respuesta a un menú ("1", "2.", "4)") al elegir cuál es el "primer
mensaje" de un caso: no dice nada de qué se trata, y usarlo rompía el título
del saludo y la búsqueda por tema de `consultar_estado_caso`.
"""

from app.db.crud.interacciones import crear_interaccion, primeros_mensajes_de_casos
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso


async def _caso(db_session, ciudadano_id) -> Caso:
    caso = Caso(
        ciudadano_id=ciudadano_id, tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    return caso


async def test_salta_la_respuesta_al_menu_y_usa_el_mensaje_real(db_session, ciudadano):
    caso = await _caso(db_session, ciudadano.id)
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="1",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="Hay un pozo en mi calle",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()

    primeros = await primeros_mensajes_de_casos(db_session, [caso.id])

    assert primeros[caso.id] == "Hay un pozo en mi calle"


async def test_si_todo_el_caso_es_solo_numeros_usa_igual_el_primero(db_session, ciudadano):
    """Sin ningún mensaje real, es preferible mostrar algo a no mostrar nada."""
    caso = await _caso(db_session, ciudadano.id)
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="4",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()

    primeros = await primeros_mensajes_de_casos(db_session, [caso.id])

    assert primeros[caso.id] == "4"


async def test_sin_respuesta_a_menu_se_queda_con_el_primero_cronologico(db_session, ciudadano):
    caso = await _caso(db_session, ciudadano.id)
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="Hola, quería reportar algo",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="Es sobre un poste quemado",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()

    primeros = await primeros_mensajes_de_casos(db_session, [caso.id])

    assert primeros[caso.id] == "Hola, quería reportar algo"
