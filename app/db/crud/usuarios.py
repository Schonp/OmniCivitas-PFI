import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Usuario
from app.schemas.usuario import UsuarioCreate


async def contar_usuarios(db: AsyncSession) -> int:
    resultado = await db.execute(select(func.count()).select_from(Usuario))
    return resultado.scalar_one()


async def obtener_usuario_por_id(db: AsyncSession, usuario_id: str | uuid.UUID) -> Usuario | None:
    return await db.get(Usuario, uuid.UUID(str(usuario_id)))


async def obtener_usuario_por_email(db: AsyncSession, email: str) -> Usuario | None:
    resultado = await db.execute(select(Usuario).where(Usuario.email == email))
    return resultado.scalar_one_or_none()


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
