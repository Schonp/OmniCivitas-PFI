import uuid

import pytest
from langchain_core.tools import ToolException
from sqlalchemy import select

from app.db.models import Auditoria, Caso, EstadoCaso, Canal, TipoCaso
from app.tools.reclamos import crear_reclamo


async def test_crear_reclamo_ciudadano_existente(db_session, ciudadano):
    resultado = await crear_reclamo(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.whatsapp,
        descripcion="La vereda está rota",
        categoria="infraestructura",
    )

    assert resultado["caso_id"] is not None
    assert resultado["tipo"] == TipoCaso.reclamo.value
    assert resultado["estado"] == EstadoCaso.abierto.value

    caso = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    assert caso is not None
    assert caso.ciudadano_id == ciudadano.id

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert any(a.accion == "creacion_reclamo" for a in auditorias)


async def test_crear_reclamo_ciudadano_inexistente(db_session):
    with pytest.raises(ToolException):
        await crear_reclamo(
            db_session,
            ciudadano_id=uuid.uuid4(),
            canal=Canal.whatsapp,
            descripcion="La vereda está rota",
            categoria="infraestructura",
        )


async def test_crear_reclamo_completa_el_caso_ya_abierto_en_vez_de_abrir_otro(
    db_session, ciudadano
):
    """El bug real: `_abrir_caso` abre un caso cuando el ciudadano recién arranca
    y todavía falta un dato para poder ejecutar (ej. la dirección). Cuando por
    fin lo da, la tool creaba OTRO caso en vez de completar el que ya estaba
    abierto: el mensaje con el dato final quedaba huérfano, desconectado del
    resto de la conversación."""
    ya_abierto = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(ya_abierto)
    await db_session.commit()

    resultado = await crear_reclamo(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.whatsapp,
        descripcion="La vereda está rota en Anchorena 2459",
        categoria="infraestructura",
        caso_id=ya_abierto.id,
    )

    assert resultado["caso_id"] == str(ya_abierto.id)

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1, "no se abrió un segundo caso"


async def test_crear_reclamo_no_reusa_un_caso_de_otro_tipo(db_session, ciudadano):
    """El caso activo puede ser de otro tipo (ej. una consulta en curso): ahí sí
    corresponde abrir uno nuevo, no pisarle el tipo al que ya existía."""
    consulta = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(consulta)
    await db_session.commit()

    resultado = await crear_reclamo(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.whatsapp,
        descripcion="La vereda está rota",
        categoria="infraestructura",
        caso_id=consulta.id,
    )

    assert resultado["caso_id"] != str(consulta.id)

    caso_nuevo = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    assert caso_nuevo.tipo == TipoCaso.reclamo


async def test_la_descripcion_queda_como_asunto_del_caso(db_session, ciudadano):
    """Es lo que identifica al reclamo cuando el ciudadano pregunta por él."""
    salida = await crear_reclamo(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.whatsapp,
        descripcion="Pozo en la calzada en Av. Rivadavia 3200",
        categoria="infraestructura",
    )

    caso = await db_session.get(Caso, uuid.UUID(salida["caso_id"]))
    assert caso.asunto == "Pozo en la calzada en Av. Rivadavia 3200"
