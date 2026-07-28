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
