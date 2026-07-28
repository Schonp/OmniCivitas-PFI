import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.crud.auditoria import listar_auditoria_de_caso
from app.db.crud.casos import cambiar_estado_caso, crear_caso, listar_casos, obtener_caso_por_id
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.models import EstadoCaso, Usuario
from app.db.session import get_db
from app.schemas.auditoria import AuditoriaOut
from app.schemas.caso import CasoCreate, CasoEstadoUpdate, CasoOut

router = APIRouter(prefix="/api/casos", tags=["casos"])


@router.post("", response_model=CasoOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: CasoCreate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> CasoOut:
    if await obtener_ciudadano_por_id(db, datos.ciudadano_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")

    return await crear_caso(db, datos, actor=usuario_actual.email)


@router.get("", response_model=list[CasoOut])
async def listar(
    estado: EstadoCaso | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[CasoOut]:
    return await listar_casos(db, estado=estado)


@router.get("/{caso_id}", response_model=CasoOut)
async def obtener(
    caso_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> CasoOut:
    caso = await obtener_caso_por_id(db, caso_id)
    if caso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    return caso


@router.patch("/{caso_id}/estado", response_model=CasoOut)
async def cambiar_estado(
    caso_id: uuid.UUID,
    datos: CasoEstadoUpdate,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> CasoOut:
    caso = await obtener_caso_por_id(db, caso_id)
    if caso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")

    return await cambiar_estado_caso(db, caso, datos.estado, actor=usuario_actual.email)


@router.get("/{caso_id}/auditoria", response_model=list[AuditoriaOut])
async def auditoria(
    caso_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[AuditoriaOut]:
    if await obtener_caso_por_id(db, caso_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caso no encontrado")
    return await listar_auditoria_de_caso(db, caso_id)
