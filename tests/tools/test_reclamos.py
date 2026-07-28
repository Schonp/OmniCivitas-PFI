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
