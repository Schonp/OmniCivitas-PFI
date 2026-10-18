from app.agents.contexto import buscar_conocimiento, nodo_contexto
from app.db.crud.interacciones import crear_interaccion
from app.db.models import ActorInteraccion, Canal, Caso, EstadoCaso, TipoCaso


def _estado(identificador: str, canal: str = "whatsapp") -> dict:
    return {
        "mensaje": "¿Cómo va mi reclamo?",
        "canal": canal,
        "identificador": identificador,
        "intencion": "consulta",
    }


async def test_contexto_ciudadano_no_identificado(db_session):
    resultado = await nodo_contexto(_estado("+5490000000000"), db_session)

    assert resultado["ciudadano_id"] is None
    assert resultado["caso_id"] is None
    assert resultado["historial"] == []


async def test_contexto_recupera_caso_abierto_e_historial(db_session, ciudadano):
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.flush()
    await crear_interaccion(
        db_session,
        caso_id=caso.id,
        contenido="La vereda está rota",
        canal=Canal.whatsapp,
        actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()

    resultado = await nodo_contexto(_estado("+5491122334455"), db_session)

    assert resultado["ciudadano_id"] == str(ciudadano.id)
    assert resultado["caso_id"] == str(caso.id)
    assert len(resultado["historial"]) == 1
    assert resultado["historial"][0]["actor"] == "ciudadano"


async def test_contexto_identifica_por_email(db_session, ciudadano):
    resultado = await nodo_contexto(
        _estado("juan.perez@test.com", canal="email"), db_session
    )
    assert resultado["ciudadano_id"] == str(ciudadano.id)


async def test_buscar_conocimiento_sin_documentos_devuelve_vacio(db_session):
    assert await buscar_conocimiento(db_session, "reclamo", "la vereda está rota") == []


async def test_contexto_recupera_el_caso_derivado_a_un_operador(db_session, ciudadano):
    """Derivado no es cerrado: el ciudadano que sigue escribiendo tiene que caer
    en el mismo caso, no en uno nuevo."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.commit()

    resultado = await nodo_contexto(
        _estado("juan.perez@test.com", canal="email"), db_session
    )

    assert resultado["caso_id"] == str(caso.id)
