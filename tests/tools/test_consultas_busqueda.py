"""Buscar el caso correcto entre varios, no siempre "el más reciente".

El bug real: un ciudadano con un reclamo del árbol caído y, más tarde, una
reserva de turno, preguntó "¿cómo sigue el árbol?" y `consultar_estado_caso`
devolvía la reserva —el caso más reciente—, sin mirar de qué hablaba.
"""

import uuid

from sqlalchemy import select

from app.db.crud.interacciones import crear_interaccion
from app.db.models import ActorInteraccion, Canal, Caso, EstadoCaso, TipoCaso
from app.tools.consultas import consultar_estado_caso


async def _caso_con_mensaje(db_session, ciudadano_id, tipo, mensaje, *, cerrado=False):
    caso = Caso(
        ciudadano_id=ciudadano_id,
        tipo=tipo,
        estado=EstadoCaso.cerrado if cerrado else EstadoCaso.abierto,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido=mensaje,
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()
    return caso


async def test_sin_pista_y_un_solo_caso_activo_lo_devuelve(db_session, ciudadano):
    caso = await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reclamo, "Hay un pozo en mi calle"
    )

    resultado = await consultar_estado_caso(db_session, ciudadano_id=ciudadano.id)

    assert resultado["referencia"] == caso.referencia
    assert resultado["varios_posibles"] is False


async def test_con_dos_casos_y_pista_por_tema_encuentra_el_correcto(db_session, ciudadano):
    """El bug real, reproducido: reclamo viejo + reserva nueva, y la pregunta es
    sobre el reclamo. Antes esto devolvía la reserva por ser lo más reciente."""
    arbol = await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reclamo, "Se cayó un árbol en Amenábar al 100"
    )
    await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reserva, "Quiero renovar el DNI el 17/9 a las 9am"
    )

    resultado = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia="como sigue el arbol caido"
    )

    assert resultado["referencia"] == arbol.referencia
    assert resultado["coincidio_la_pista"] is True
    assert resultado["varios_posibles"] is False


async def test_pista_por_numero_de_referencia_sin_el_prefijo(db_session, ciudadano):
    """La gente copia el número sin el "REC-": tiene que igual encontrarlo."""
    caso = await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reclamo, "Hay un pozo en mi calle"
    )
    await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reserva, "Quiero un turno para el CeSAC"
    )

    referencia = caso.referencia.split("-")[1].lower()
    resultado = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia=referencia
    )

    assert resultado["referencia"] == caso.referencia


async def test_sin_pista_y_dos_casos_activos_no_adivina(db_session, ciudadano):
    await _caso_con_mensaje(db_session, ciudadano.id, TipoCaso.reclamo, "Hay un pozo")
    await _caso_con_mensaje(db_session, ciudadano.id, TipoCaso.reserva, "Quiero un turno")

    resultado = await consultar_estado_caso(db_session, ciudadano_id=ciudadano.id)

    assert resultado["varios_posibles"] is True
    assert len(resultado["casos"]) == 2


async def test_pista_sin_coincidencia_prefiere_lo_activo_sobre_lo_cerrado(db_session, ciudadano):
    await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reclamo, "Vereda rota", cerrado=True
    )
    activo = await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reserva, "Quiero un turno"
    )

    resultado = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia="algo que no coincide con nada"
    )

    assert resultado["referencia"] == activo.referencia
    assert resultado["coincidio_la_pista"] is False


async def test_puede_encontrar_un_caso_cerrado_si_lo_menciona(db_session, ciudadano):
    """Antes la búsqueda no distinguía: esto ya funcionaba. Sigue andando con
    la reescritura: preguntar por un trámite viejo tiene que encontrarlo aunque
    ya esté cerrado."""
    cerrado = await _caso_con_mensaje(
        db_session, ciudadano.id, TipoCaso.reclamo,
        "Se cayó un árbol en Amenábar al 100", cerrado=True,
    )
    await _caso_con_mensaje(db_session, ciudadano.id, TipoCaso.reserva, "Quiero un turno")

    resultado = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia="el arbol caido"
    )

    assert resultado["referencia"] == cerrado.referencia
    assert resultado["estado"] == EstadoCaso.cerrado.value


async def test_la_respuesta_al_menu_no_se_usa_como_tema_del_caso(db_session, ciudadano):
    """El bug relacionado: el caso arranca con un "1" (elección del menú) y ese
    "1" quedaba como "primer mensaje" del caso, sin nada con que emparejar
    después. Tiene que saltearse y usar el mensaje real."""
    caso = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="1",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await crear_interaccion(
        db_session, caso_id=caso.id, contenido="Se cayó un árbol en Amenábar al 100",
        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()
    await _caso_con_mensaje(db_session, ciudadano.id, TipoCaso.reserva, "Quiero un turno")

    resultado = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia="el arbol caido en amenabar"
    )

    assert resultado["referencia"] == caso.referencia
    assert resultado["varios_posibles"] is False
