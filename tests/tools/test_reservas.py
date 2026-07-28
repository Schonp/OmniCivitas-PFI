import uuid

from sqlalchemy import select

from app.db.models import Auditoria, Canal, Caso, TipoCaso
from app.tools.reservas import crear_reserva


async def test_crear_reserva_registra_caso_y_auditoria(db_session, ciudadano):
    resultado = await crear_reserva(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.email,
        descripcion="Turno para renovar licencia",
        fecha_solicitada="2026-08-15",
    )

    assert resultado["tipo"] == TipoCaso.reserva.value
    assert resultado["fecha_solicitada"] == "2026-08-15"

    caso = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    assert caso is not None

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert any(
        a.accion == "creacion_reserva" and a.metadata_["fecha_solicitada"] == "2026-08-15"
        for a in auditorias
    )
