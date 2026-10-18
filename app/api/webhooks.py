"""Webhooks de los proveedores de canal.

Son endpoints públicos: no los llama el panel ni el ciudadano, los llama Meta.
La autenticación no es JWT sino la firma del proveedor, que se valida sobre el
cuerpo crudo antes de tocar la base. Meta reintenta si no recibe 2xx rápido, así
que la respuesta al ciudadano se manda en segundo plano.
"""

import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import salida, whatsapp
from app.core.rate_limit import check_rate_limit
from app.db.crud.ciudadanos import obtener_ciudadano_por_telefono
from app.db.models import Canal
from app.db.session import async_session_factory, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _sin_contenido() -> Response:
    """Meta reintenta si no recibe 2xx; se responde vacío porque la respuesta al
    ciudadano se manda por la API, no en el cuerpo del webhook.

    Devuelve una instancia nueva en cada llamada: FastAPI le adosa las tareas de
    background al objeto response, así que compartir uno solo las mezclaría
    entre requests.
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _responder_por_whatsapp(telefono: str, texto: str, caso_id: str | None) -> None:
    """Transmite la respuesta del agente después de haberle contestado a Meta.

    Abre su propia sesión: corre como tarea de fondo, cuando la del request ya
    se cerró. Pasa por `salida` en vez de llamar a `whatsapp.enviar_mensaje`
    directo para que un fallo de envío quede auditado y no reviente el webhook:
    con el token vencido, la respuesta terminaba en un traceback de ASGI y el
    ciudadano quedaba esperando algo que nadie sabía que no había salido.
    """
    async with async_session_factory() as db:
        ciudadano = await obtener_ciudadano_por_telefono(db, telefono)
        if ciudadano is None:
            logger.error("webhook whatsapp: no se encontró al ciudadano para responder")
            return
        await salida.responder_al_ciudadano(
            db,
            canal=Canal.whatsapp,
            ciudadano=ciudadano,
            texto=texto,
            caso_id=uuid.UUID(caso_id) if caso_id else None,
        )


@router.get("/whatsapp", response_class=Response)
async def whatsapp_verificacion(
    modo: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    desafio: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Alta del webhook: Meta pega un GET y espera que le devuelvan el desafío."""
    resultado = whatsapp.verificar_webhook(modo, token, desafio)
    if resultado is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verificación rechazada"
        )
    return Response(content=resultado, media_type="text/plain")


@router.post("/whatsapp", status_code=status.HTTP_204_NO_CONTENT)
async def whatsapp_entrante(
    request: Request,
    tareas: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Recibe los mensajes de WhatsApp que reenvía Meta."""
    # La firma se calcula sobre el cuerpo crudo: hay que leerlo antes de parsear.
    crudo = await request.body()
    if not whatsapp.validar_firma(crudo, request.headers.get("X-Hub-Signature-256")):
        logger.warning("webhook whatsapp: firma inválida, se descarta el envío")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Firma inválida"
        )

    try:
        payload = json.loads(crudo.decode("utf-8"))
    except ValueError:
        logger.warning("webhook whatsapp: cuerpo que no es JSON")
        return _sin_contenido()

    # El mismo webhook trae acuses de entrega además de mensajes: se descartan.
    for entrante in whatsapp.extraer_mensajes(payload):
        if not check_rate_limit(f"whatsapp:{entrante.telefono}"):
            logger.warning("webhook whatsapp: rate limit alcanzado")
            continue

        final = await whatsapp.recibir_mensaje(
            db,
            telefono=entrante.telefono,
            mensaje=entrante.texto,
            nombre=entrante.nombre,
        )
        respuesta = final.get("respuesta")
        if respuesta:
            tareas.add_task(
                _responder_por_whatsapp,
                entrante.telefono,
                respuesta,
                final.get("caso_id"),
            )

    return _sin_contenido()
