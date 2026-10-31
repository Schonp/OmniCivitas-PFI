"""Teléfono web: una llamada de voz desde el navegador, para probar y mostrar el
canal de voz sin una línea de Twilio.

El navegador habla el mismo protocolo que Twilio Media Streams (`start`,
`media` con mulaw a 8 kHz en chunks de 20 ms, `stop`), así que la llamada pasa
por exactamente el mismo código que una llamada real (`atender_stream`):
detector de turno, ASR, grafo, TTS. Lo único distinto es quién fija el
teléfono del ciudadano y los avisos de subtítulos y estado que recibe la
página.

No es un canal del producto: lo usa una persona del panel para simular una
llamada desde un número. Por eso pide un usuario del panel y el teléfono lo
fija el servidor al autenticar, no un parámetro del `start` que cualquiera
podría mandar.
"""

import logging
import re

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.webhooks import atender_stream
from app.channels.whatsapp import normalizar_telefono
from app.core.security import decodificar_token
from app.db.crud.usuarios import obtener_usuario_por_id
from app.db.models import RolUsuario, Usuario
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telefono-web", tags=["telefono-web"])

TELEFONO_VALIDO = re.compile(r"\+\d{8,15}")
ROLES_PERMITIDOS = (RolUsuario.operador, RolUsuario.supervisor)
# Códigos de cierre propios (rango 4000-4999 que reserva el protocolo para la
# aplicación): la página los muestra en vez de un corte sin explicación.
CIERRE_SIN_AUTORIZACION = 4401
CIERRE_TELEFONO_INVALIDO = 4422


async def _usuario_del_token(token: str) -> Usuario | None:
    try:
        datos = decodificar_token(token)
    except jwt.PyJWTError:
        return None
    if datos.get("tipo") != "access":
        return None
    async with async_session_factory() as db:
        usuario = await obtener_usuario_por_id(db, datos["sub"])
    if usuario is None or not usuario.activo or usuario.rol not in ROLES_PERMITIDOS:
        return None
    return usuario


@router.websocket("/stream")
async def telefono_web(websocket: WebSocket) -> None:
    """El primer mensaje es `{"event": "auth", "token", "telefono"}`. El token
    va en el mensaje y no en la URL para que no quede en los logs de acceso."""
    await websocket.accept()
    try:
        primero = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    if primero.get("event") != "auth":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    usuario = await _usuario_del_token(str(primero.get("token") or ""))
    if usuario is None:
        await websocket.close(code=CIERRE_SIN_AUTORIZACION)
        return
    telefono = normalizar_telefono(str(primero.get("telefono") or ""))
    if not TELEFONO_VALIDO.fullmatch(telefono):
        await websocket.close(code=CIERRE_TELEFONO_INVALIDO)
        return

    logger.info("teléfono web: llamada simulada por el usuario %s", usuario.id)

    async def avisar(evento: dict) -> None:
        await websocket.send_json(evento)

    await websocket.send_json({"event": "conectado"})
    await atender_stream(websocket, telefono_fijo=telefono, avisar=avisar)
