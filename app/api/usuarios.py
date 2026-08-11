from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import requiere_rol
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.usuario import UsuarioOut

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])


@router.get("", response_model=list[UsuarioOut])
async def listar(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> list[UsuarioOut]:
    """Operadores activos, para que el supervisor pueda distribuir los casos."""
    consulta = select(Usuario).where(Usuario.activo.is_(True)).order_by(Usuario.nombre)
    return list((await db.execute(consulta)).scalars().all())
