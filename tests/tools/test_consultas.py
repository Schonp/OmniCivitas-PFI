import uuid

from sqlalchemy import select

from app.db.models import Auditoria, Canal, Caso, TipoCaso
from app.tools.consultas import consultar_estado_caso


async def test_consultar_estado_sin_casos(db_session, ciudadano):
    resultado = await consultar_estado_caso(db_session, ciudadano_id=ciudadano.id)
    assert resultado["tiene_casos"] is False


async def test_consultar_estado_con_caso_audita(db_session, ciudadano):
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.commit()

    resultado = await consultar_estado_caso(db_session, ciudadano_id=ciudadano.id)

    assert resultado["tiene_casos"] is True
    assert resultado["caso_id"] == str(caso.id)
    assert resultado["estado"] == caso.estado.value

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert any(a.accion == "consulta_estado" for a in auditorias)


async def test_consultar_estado_puede_excluir_el_caso_de_la_pregunta(db_session, ciudadano):
    """El caso abierto con "¿cómo va el reclamo del pozo?" coincide por tema con
    el reclamo del pozo: sin excluirlo, la consulta se encontraría a sí misma."""
    from app.db.models import Canal, Caso, TipoCaso
    from app.tools.consultas import consultar_estado_caso

    reclamo = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo, canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp, asunto="Pozo en la calzada",
    )
    pregunta = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.consulta, canal_origen=Canal.email,
        canal_actual=Canal.email, asunto="Cómo va el reclamo del pozo",
    )
    db_session.add_all([reclamo, pregunta])
    await db_session.commit()

    salida = await consultar_estado_caso(
        db_session, ciudadano_id=ciudadano.id, referencia="el reclamo del pozo", excluir=pregunta.id
    )

    assert salida["varios_posibles"] is False
    assert salida["referencia"] == reclamo.referencia
