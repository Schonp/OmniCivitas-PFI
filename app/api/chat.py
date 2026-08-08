import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import web
from app.core.dependencies import get_ciudadano_actual
from app.core.rate_limit import check_rate_limit
from app.core.security import crear_chat_token
from app.db.models import Ciudadano
from app.db.session import get_db
from app.schemas.chat import (
    HistorialChat,
    InicioSesionChat,
    MensajeChat,
    RespuestaChat,
    SesionChat,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _verificar_limite(clave: str) -> None:
    if not check_rate_limit(f"chat:{clave}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Intente nuevamente en un minuto.",
        )


@router.post("/sesion", response_model=SesionChat, status_code=status.HTTP_201_CREATED)
async def iniciar_sesion(
    datos: InicioSesionChat,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SesionChat:
    """Identifica al ciudadano en el canal web y abre una sesión de chat.
    Endpoint público: el ciudadano no es un usuario del panel."""
    _verificar_limite(request.client.host if request.client else "desconocido")

    ciudadano = await web.identificar_ciudadano(db, datos)
    return SesionChat(
        token=crear_chat_token(str(ciudadano.id)),
        ciudadano_id=ciudadano.id,
        nombre=ciudadano.nombre,
    )


@router.post("/mensaje", response_model=RespuestaChat)
async def enviar_mensaje(
    datos: MensajeChat,
    db: AsyncSession = Depends(get_db),
    ciudadano: Ciudadano = Depends(get_ciudadano_actual),
) -> RespuestaChat:
    _verificar_limite(str(ciudadano.id))

    final = await web.recibir_mensaje(db, ciudadano=ciudadano, mensaje=datos.mensaje)
    caso_id = final.get("caso_id")
    return RespuestaChat(
        respuesta=final.get("respuesta") or "",
        caso_id=uuid.UUID(caso_id) if caso_id else None,
        intencion=final.get("intencion"),
        escalado=bool(final.get("requiere_escalado")),
    )


@router.get("/historial", response_model=HistorialChat)
async def historial(
    db: AsyncSession = Depends(get_db),
    ciudadano: Ciudadano = Depends(get_ciudadano_actual),
) -> HistorialChat:
    caso, interacciones = await web.obtener_conversacion(db, ciudadano)
    return HistorialChat(
        caso_id=caso.id if caso else None,
        estado=caso.estado if caso else None,
        interacciones=interacciones,
    )
