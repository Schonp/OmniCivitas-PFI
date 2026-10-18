import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Caso, EstadoCaso, RolUsuario, Usuario
from app.schemas.usuario import UsuarioCreate


async def contar_usuarios(db: AsyncSession) -> int:
    resultado = await db.execute(select(func.count()).select_from(Usuario))
    return resultado.scalar_one()


async def obtener_usuario_por_id(db: AsyncSession, usuario_id: str | uuid.UUID) -> Usuario | None:
    return await db.get(Usuario, uuid.UUID(str(usuario_id)))


async def obtener_usuario_por_email(db: AsyncSession, email: str) -> Usuario | None:
    resultado = await db.execute(select(Usuario).where(Usuario.email == email))
    return resultado.scalar_one_or_none()


async def elegir_operador_con_menos_casos_activos(db: AsyncSession) -> Usuario | None:
    """El operador activo con menos casos sin cerrar a cargo, para repartir la
    carga al escalar automáticamente. Nunca un supervisor: el supervisor ve y
    reparte el organismo entero, no atiende su propia bandeja.

    Empate → el de alta más antigua, para que la elección sea determinística
    (reproducible en los tests) y no dependa de un orden arbitrario de Postgres.
    None si no hay ningún operador activo: el caso queda sin asignar, como
    antes de esta función existir.
    """
    casos_por_operador = (
        select(Caso.operador_asignado_id, func.count(Caso.id).label("activos"))
        .where(Caso.estado != EstadoCaso.cerrado, Caso.operador_asignado_id.is_not(None))
        .group_by(Caso.operador_asignado_id)
        .subquery()
    )
    consulta = (
        select(Usuario)
        .outerjoin(casos_por_operador, casos_por_operador.c.operador_asignado_id == Usuario.id)
        .where(Usuario.rol == RolUsuario.operador, Usuario.activo.is_(True))
        .order_by(
            func.coalesce(casos_por_operador.c.activos, 0).asc(),
            Usuario.created_at.asc(),
        )
        .limit(1)
    )
    return (await db.execute(consulta)).scalars().first()


async def crear_usuario(db: AsyncSession, datos: UsuarioCreate) -> Usuario:
    usuario = Usuario(
        email=datos.email,
        nombre=datos.nombre,
        hashed_password=hash_password(datos.password),
        rol=datos.rol,
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)
    return usuario
