"""Reparto de carga al escalar: el operador con menos casos sin cerrar,
nunca un supervisor. Empate → el de alta más antigua, determinístico."""

from app.db.crud.usuarios import elegir_operador_con_menos_casos_activos
from app.db.models import Canal, Caso, EstadoCaso, RolUsuario, TipoCaso, Usuario
from app.core.security import hash_password


async def _operador(db_session, email: str, *, activo: bool = True) -> Usuario:
    usuario = Usuario(
        email=email, nombre=email, hashed_password=hash_password("x"),
        rol=RolUsuario.operador, activo=activo,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


async def _caso_asignado(db_session, ciudadano_id, operador_id, estado=EstadoCaso.en_progreso):
    caso = Caso(
        ciudadano_id=ciudadano_id, tipo=TipoCaso.reclamo, estado=estado,
        canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp,
        operador_asignado_id=operador_id,
    )
    db_session.add(caso)
    await db_session.commit()
    return caso


async def test_sin_operadores_activos_devuelve_none(db_session):
    assert await elegir_operador_con_menos_casos_activos(db_session) is None


async def test_ignora_a_los_supervisores(db_session, usuario_admin):
    """`usuario_admin` (fixture del conftest) es supervisor: no debe elegirse
    aunque sea el único usuario del sistema."""
    assert await elegir_operador_con_menos_casos_activos(db_session) is None


async def test_ignora_operadores_inactivos(db_session):
    await _operador(db_session, "inactivo@test.com", activo=False)

    assert await elegir_operador_con_menos_casos_activos(db_session) is None


async def test_elige_al_que_tiene_menos_casos_activos(db_session, ciudadano):
    cargado = await _operador(db_session, "cargado@test.com")
    libre = await _operador(db_session, "libre@test.com")
    await _caso_asignado(db_session, ciudadano.id, cargado.id)
    await _caso_asignado(db_session, ciudadano.id, cargado.id)
    await _caso_asignado(db_session, ciudadano.id, libre.id)

    elegido = await elegir_operador_con_menos_casos_activos(db_session)

    assert elegido.id == libre.id


async def test_un_caso_cerrado_no_cuenta_como_carga(db_session, ciudadano):
    """Cerrar casos tiene que aliviar la carga del operador para el reparto
    siguiente: si no, un operador productivo terminaría "más cargado" que uno
    que nunca resuelve nada."""
    con_cerrados = await _operador(db_session, "cerro-varios@test.com")
    sin_nada = await _operador(db_session, "sin-nada@test.com")
    await _caso_asignado(db_session, ciudadano.id, con_cerrados.id, estado=EstadoCaso.cerrado)
    await _caso_asignado(db_session, ciudadano.id, con_cerrados.id, estado=EstadoCaso.cerrado)

    elegido = await elegir_operador_con_menos_casos_activos(db_session)

    # Los dos tienen 0 casos activos: empate, gana el de alta más antigua.
    assert elegido.id == con_cerrados.id


async def test_empate_elige_al_de_alta_mas_antigua(db_session):
    primero = await _operador(db_session, "primero@test.com")
    await _operador(db_session, "segundo@test.com")

    elegido = await elegir_operador_con_menos_casos_activos(db_session)

    assert elegido.id == primero.id
