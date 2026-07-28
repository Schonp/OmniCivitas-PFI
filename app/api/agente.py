import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import procesar_mensaje
from app.core.dependencies import get_current_user
from app.db.models import Usuario
from app.db.session import get_db
from app.schemas.agente import MensajeEntrante, RespuestaAgente

router = APIRouter(prefix="/api/agente", tags=["agente"])


@router.post("/mensaje", response_model=RespuestaAgente)
async def enviar_mensaje(
    datos: MensajeEntrante,
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> RespuestaAgente:
    """Entry point de prueba del orquestador hasta que existan los webhooks de
    canales (Fases 4-5). Simula un mensaje entrante de un ciudadano."""
    final = await procesar_mensaje(
        db,
        mensaje=datos.mensaje,
        canal=datos.canal,
        identificador=datos.identificador,
    )
    caso_id = final.get("caso_id")
    return RespuestaAgente(
        respuesta=final.get("respuesta") or "",
        caso_id=uuid.UUID(caso_id) if caso_id else None,
        intencion=final.get("intencion"),
        confianza=final.get("confianza") or 0.0,
        escalado=bool(final.get("requiere_escalado")),
    )
