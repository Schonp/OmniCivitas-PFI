from app.agents.contexto import buscar_conocimiento, nodo_contexto
from app.db.crud.conocimiento import crear_documento
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


async def test_el_dni_sigue_el_pedido_del_caso_abierto(db_session):
    """Pasó por voz: después de pedir un turno, el mensaje con el DNI salió
    "reclamo" y el turno se registró como reclamo. La respuesta al pedido de
    datos lleva la intención del pedido que la motivó."""
    from app.db.crud.ciudadanos import documento_provisorio
    from app.db.models import Ciudadano

    provisorio = Ciudadano(
        nombre="Laura", documento=documento_provisorio("+5491100008899"), telefono="+5491100008899"
    )
    db_session.add(provisorio)
    await db_session.flush()
    caso = Caso(
        ciudadano_id=provisorio.id,
        tipo=TipoCaso.reserva,
        canal_origen=Canal.voz,
        canal_actual=Canal.voz,
    )
    db_session.add(caso)
    await db_session.commit()
    estado = {
        "mensaje": "Me llamo Laura Prueba y mi documento es 30-885-311.",
        "canal": "voz",
        "identificador": "+5491100008899",
        "intencion": "reclamo",
    }

    resultado = await nodo_contexto(estado, db_session)

    assert resultado["caso_id"] == str(caso.id)
    assert resultado["intencion"] == "reserva"


async def test_contexto_trae_las_pautas_generales(db_session, ciudadano):
    """Las pautas llegan aunque el mensaje no las mencione."""
    await crear_documento(
        db_session, titulo="Trato", contenido="Tratar de usted.", general=True
    )

    resultado = await nodo_contexto(_estado("+5491122334455"), db_session)

    assert resultado["pautas"] == ["Trato: Tratar de usted."]


async def test_contexto_trae_las_pautas_aunque_no_reconozca_al_ciudadano(db_session):
    await crear_documento(
        db_session, titulo="Trato", contenido="Tratar de usted.", general=True
    )

    resultado = await nodo_contexto(_estado("+5490000000000"), db_session)

    assert resultado["pautas"] == ["Trato: Tratar de usted."]
