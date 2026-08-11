import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentoConocimiento

# Tamaño del fragmento que entra al contexto del LLM por documento.
MAX_CARACTERES_FRAGMENTO = 1500
MAX_DOCUMENTOS_CONTEXTO = 3
MIN_LARGO_PALABRA = 4


async def listar_documentos(db: AsyncSession) -> list[DocumentoConocimiento]:
    consulta = select(DocumentoConocimiento).order_by(DocumentoConocimiento.created_at.desc())
    return list((await db.execute(consulta)).scalars().all())


async def crear_documento(
    db: AsyncSession, *, titulo: str, contenido: str, nombre_archivo: str | None = None
) -> DocumentoConocimiento:
    documento = DocumentoConocimiento(
        titulo=titulo, contenido=contenido, nombre_archivo=nombre_archivo
    )
    db.add(documento)
    await db.commit()
    await db.refresh(documento)
    return documento


async def borrar_documento(db: AsyncSession, documento_id: uuid.UUID) -> bool:
    documento = await db.get(DocumentoConocimiento, documento_id)
    if documento is None:
        return False
    await db.delete(documento)
    await db.commit()
    return True


async def buscar_documentos_relevantes(db: AsyncSession, mensaje: str) -> list[str]:
    """Recuperación léxica simple: documentos cuyo título o contenido mencionan
    alguna palabra del mensaje. La búsqueda semántica con pgvector queda para la
    fase de RAG; la interfaz (mensaje → fragmentos) no cambia.
    """
    palabras = {
        palabra.strip(".,;:¿?¡!()").lower()
        for palabra in mensaje.split()
        if len(palabra.strip(".,;:¿?¡!()")) >= MIN_LARGO_PALABRA
    }
    if not palabras:
        return []

    condiciones = []
    for palabra in palabras:
        patron = f"%{palabra}%"
        condiciones.append(DocumentoConocimiento.titulo.ilike(patron))
        condiciones.append(DocumentoConocimiento.contenido.ilike(patron))

    consulta = (
        select(DocumentoConocimiento)
        .where(or_(*condiciones))
        .order_by(DocumentoConocimiento.created_at.desc())
        .limit(MAX_DOCUMENTOS_CONTEXTO)
    )
    documentos = (await db.execute(consulta)).scalars().all()
    return [
        f"{documento.titulo}: {documento.contenido[:MAX_CARACTERES_FRAGMENTO]}"
        for documento in documentos
    ]
