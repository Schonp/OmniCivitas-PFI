"""Identificación del ciudadano: el alta por un canal externo es provisoria
hasta que informa su documento."""

from app.db.crud.ciudadanos import (
    crear_ciudadano,
    documento_provisorio,
    esta_identificado,
    identificar_ciudadano,
    obtener_ciudadano_por_email,
)
from app.db.models import Ciudadano
from app.schemas.ciudadano import CiudadanoCreate

CORREO = "vecina@correo.test"


def test_el_alta_por_canal_no_cuenta_como_identificado():
    provisorio = Ciudadano(documento=documento_provisorio(CORREO), nombre="Sin identificar")
    con_dni = Ciudadano(documento="28456789", nombre="Marta Ruiz")

    assert esta_identificado(provisorio) is False
    assert esta_identificado(con_dni) is True


async def test_identificar_reemplaza_el_documento_provisorio(db_session):
    ciudadano = await crear_ciudadano(
        db_session,
        CiudadanoCreate(
            documento=documento_provisorio(CORREO), nombre="Sin identificar", email=CORREO
        ),
    )

    actualizado = await identificar_ciudadano(
        db_session, ciudadano.id, documento="28456789", nombre="Marta Ruiz"
    )

    assert actualizado.id == ciudadano.id
    assert actualizado.documento == "28456789"
    assert actualizado.nombre == "Marta Ruiz"
    assert esta_identificado(actualizado) is True


async def test_si_el_documento_ya_existe_se_suma_el_contacto_a_esa_persona(db_session):
    """Es el mismo vecino escribiendo desde un medio nuevo, no uno distinto:
    el contacto se agrega al registro que ya estaba en el padrón."""
    del_padron = await crear_ciudadano(
        db_session,
        CiudadanoCreate(documento="28456789", nombre="Marta Ruiz", telefono="+5491133334444"),
    )
    provisorio = await crear_ciudadano(
        db_session,
        CiudadanoCreate(
            documento=documento_provisorio(CORREO), nombre="Sin identificar", email=CORREO
        ),
    )

    resultado = await identificar_ciudadano(
        db_session, provisorio.id, documento="28456789", nombre="Marta Ruiz"
    )

    assert resultado.id == del_padron.id
    assert resultado.email == CORREO
    assert resultado.telefono == "+5491133334444"
    # Y el correo ahora resuelve a la persona del padrón, no al registro provisorio.
    assert (await obtener_ciudadano_por_email(db_session, CORREO)).id == del_padron.id


# --- Referencia legible del caso -------------------------------------------


def test_la_referencia_del_caso_es_legible_y_lleva_prefijo_por_tipo():
    """Al ciudadano se le informa esta referencia, no el UUID interno."""
    import uuid as _uuid

    from app.db.models import Canal, Caso, TipoCaso

    identificador = _uuid.UUID("5072bfa2-888e-4ae9-ab0a-e42136a5c30d")
    for tipo, prefijo in (
        (TipoCaso.reclamo, "REC"),
        (TipoCaso.reserva, "RES"),
        (TipoCaso.consulta, "CON"),
        (TipoCaso.tramite, "TRA"),
    ):
        caso = Caso(
            id=identificador, tipo=tipo, canal_origen=Canal.email, canal_actual=Canal.email
        )
        assert caso.referencia == f"{prefijo}-5072BFA2"


async def test_al_sumar_el_contacto_los_casos_del_provisorio_pasan_a_la_persona(db_session):
    """Lo que el vecino contó antes de identificarse es suyo: si el caso queda en
    el registro provisorio, que ya no es alcanzable por ningún canal, se pierde."""
    from sqlalchemy import select

    from app.db.models import Canal, Caso, TipoCaso

    del_padron = await crear_ciudadano(
        db_session,
        CiudadanoCreate(documento="28456789", nombre="Marta Ruiz", telefono="+5491133334444"),
    )
    provisorio = await crear_ciudadano(
        db_session,
        CiudadanoCreate(
            documento=documento_provisorio(CORREO), nombre="Sin identificar", email=CORREO
        ),
    )
    caso = Caso(
        ciudadano_id=provisorio.id, tipo=TipoCaso.reclamo, canal_origen=Canal.email, canal_actual=Canal.email
    )
    db_session.add(caso)
    await db_session.flush()

    await identificar_ciudadano(db_session, provisorio.id, documento="28456789", nombre="Marta Ruiz")

    duenio = (await db_session.execute(select(Caso.ciudadano_id).where(Caso.id == caso.id))).scalar_one()
    assert duenio == del_padron.id
