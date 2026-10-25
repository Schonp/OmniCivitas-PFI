import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, requiere_rol
from app.db.crud.conocimiento import borrar_documento, crear_documento, listar_documentos
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.conocimiento import DocumentoCreate, DocumentoOut

router = APIRouter(prefix="/api/conocimiento", tags=["conocimiento"])

solo_supervisor = requiere_rol(RolUsuario.supervisor)


@router.get("", response_model=list[DocumentoOut])
async def listar(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[DocumentoOut]:
    return [DocumentoOut.model_validate(doc) for doc in await listar_documentos(db)]


@router.post("", response_model=DocumentoOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: DocumentoCreate,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> DocumentoOut:
    """El archivo lo lee el navegador y llega como texto: el contenido es el mismo
    se cargue por archivo o pegando texto."""
    documento = await crear_documento(
        db,
        titulo=datos.titulo,
        contenido=datos.contenido,
        nombre_archivo=datos.nombre_archivo,
        general=datos.general,
    )
    return DocumentoOut.model_validate(documento)


@router.delete("/{documento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(
    documento_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(solo_supervisor),
) -> None:
    if not await borrar_documento(db, documento_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado"
        )
