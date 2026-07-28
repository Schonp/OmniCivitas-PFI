import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.crud.ciudadanos import crear_ciudadano, obtener_ciudadano_por_id
from app.db.session import get_db
from app.schemas.ciudadano import CiudadanoCreate, CiudadanoOut

router = APIRouter(prefix="/api/ciudadanos", tags=["ciudadanos"])


@router.post("", response_model=CiudadanoOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: CiudadanoCreate,
    db: AsyncSession = Depends(get_db),
    _usuario=Depends(get_current_user),
) -> CiudadanoOut:
    return await crear_ciudadano(db, datos)


@router.get("/{ciudadano_id}", response_model=CiudadanoOut)
async def obtener(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario=Depends(get_current_user),
) -> CiudadanoOut:
    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")
    return ciudadano
