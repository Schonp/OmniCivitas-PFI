import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agrupador import agrupar_reclamos
from app.core.dependencies import requiere_rol
from app.db.crud.casos import obtener_casos_por_ids
from app.db.models import GrupoReclamo, RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.caso import CasoOut
from app.schemas.grupo_reclamo import GrupoReclamoOut

router = APIRouter(prefix="/api/reclamos", tags=["reclamos"])

# La vista de reclamos en común cruza casos de todos los operadores: es una
# herramienta de análisis del organismo, no de la bandeja individual.
solo_supervisor = requiere_rol(RolUsuario.supervisor)


async def _hidratar(db: AsyncSession, grupos: list[GrupoReclamo]) -> list[GrupoReclamoOut]:
    salida = []
    for grupo in grupos:
        casos = await obtener_casos_por_ids(
            db, [uuid.UUID(caso_id) for caso_id in grupo.caso_ids]
        )
        salida.append(
            GrupoReclamoOut(
                id=grupo.id,
                tema=grupo.tema,
                casos=[CasoOut.model_validate(caso) for caso in casos],
                generado_en=grupo.generado_en,
            )
        )
    return salida


@router.get("/grupos", response_model=list[GrupoReclamoOut])
async def listar_grupos(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> list[GrupoReclamoOut]:
    grupos = list(
        (await db.execute(select(GrupoReclamo).order_by(GrupoReclamo.tema))).scalars().all()
    )
    return await _hidratar(db, grupos)


@router.post("/grupos/generar", response_model=list[GrupoReclamoOut])
async def generar_grupos(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> list[GrupoReclamoOut]:
    """Reagrupa los reclamos abiertos con IA y reemplaza la agrupación anterior."""
    try:
        grupos = await agrupar_reclamos(db)
    except Exception as excepcion:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El servicio de IA no está disponible: intente de nuevo más tarde",
        ) from excepcion
    return await _hidratar(db, grupos)
