import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import borrar_hilos
from app.core.dependencies import get_current_user, requiere_rol
from app.db.crud.ciudadanos import crear_ciudadano, obtener_ciudadano_por_id
from app.db.crud.titulares import dar_de_baja_titular, datos_del_titular, rectificar_titular
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.ciudadano import CiudadanoCreate, CiudadanoOut, CiudadanoRectificacion

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


# --- Derechos del titular (Ley 25.326) ------------------------------------------
# Solo el supervisor: el operador trabaja los casos sin ver datos de contacto, y
# exportar o borrar los datos de una persona no es parte de atender un caso.


async def _titular(db: AsyncSession, ciudadano_id: uuid.UUID):
    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ciudadano no encontrado")
    return ciudadano


@router.get("/{ciudadano_id}/datos")
async def exportar_datos(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> dict:
    """Derecho de acceso (RF-14): todo lo que el sistema guarda sobre el titular."""
    return await datos_del_titular(db, await _titular(db, ciudadano_id))


@router.patch("/{ciudadano_id}", response_model=CiudadanoOut)
async def rectificar(
    ciudadano_id: uuid.UUID,
    datos: CiudadanoRectificacion,
    db: AsyncSession = Depends(get_db),
    supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> CiudadanoOut:
    """Derecho de rectificación (RF-14)."""
    ciudadano = await _titular(db, ciudadano_id)
    return await rectificar_titular(
        db, ciudadano, actor=supervisor.email, nombre=datos.nombre, email=datos.email, telefono=datos.telefono
    )


@router.post("/{ciudadano_id}/baja", status_code=status.HTTP_204_NO_CONTENT)
async def dar_de_baja(
    ciudadano_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    supervisor: Usuario = Depends(requiere_rol(RolUsuario.supervisor)),
) -> None:
    """Derecho de supresión (RF-13): borra sus datos y anonimiza su historial."""
    hilos = await dar_de_baja_titular(db, await _titular(db, ciudadano_id), actor=supervisor.email)
    await borrar_hilos(hilos)

