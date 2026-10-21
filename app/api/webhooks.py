"""Webhooks de los proveedores de canal.

Son endpoints públicos: no los llama el panel ni el ciudadano, los llama Meta.
La autenticación no es JWT sino la firma del proveedor, que se valida sobre el
cuerpo crudo antes de tocar la base. Meta reintenta si no recibe 2xx rápido, así
que la respuesta al ciudadano se manda en segundo plano.
"""

import base64
import json
import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import salida, voz, whatsapp
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


@router.post("/voz", response_class=Response)
async def voz_entrante(request: Request) -> Response:
    """Alta de llamada: Twilio pega acá al empezar una llamada y espera TwiML
    que le diga qué hacer. A diferencia de WhatsApp, acá no se procesa ningún
    mensaje -- solo se conecta el WebSocket de Media Streams; toda la
    conversación corre sobre esa conexión, no sobre más webhooks de este
    endpoint."""
    form = await request.form()
    parametros = {clave: str(valor) for clave, valor in form.items()}
    if not voz.validar_firma(
        str(request.url), parametros, request.headers.get("X-Twilio-Signature")
    ):
        logger.warning("webhook voz: firma inválida, se rechaza la llamada")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Firma inválida")

    telefono = parametros.get("From", "")
    if not telefono:
        logger.error("webhook voz: la llamada no trae 'From'")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta 'From'")

    return Response(content=voz.twiml_conectar_stream(telefono), media_type="application/xml")


async def _procesar_turno_de_voz(
    websocket: WebSocket, stream_sid: str | None, telefono: str | None, audio_mulaw: bytes
) -> None:
    """Un turno completo: ASR -> grafo -> TTS -> audio de vuelta. No propaga
    excepciones: un fallo puntual de ASR/TTS no debe cortar la llamada entera,
    el ciudadano simplemente no recibe respuesta a ese turno puntual y puede
    volver a intentar."""
    if not telefono or not stream_sid or not audio_mulaw:
        return

    wav_entrada = voz.mulaw_a_wav(audio_mulaw)
    try:
        texto = await voz.transcribir(wav_entrada)
    except Exception:
        logger.exception("canal voz: fallo el ASR")
        return
    logger.info("canal voz: transcripto=%r", texto)
    if not texto.strip():
        return

    async with async_session_factory() as db:
        final = await voz.recibir_turno(db, telefono=telefono, mensaje=texto)

    respuesta = final.get("respuesta")
    logger.info("canal voz: respuesta del grafo=%r", respuesta)
    if not respuesta:
        return

    try:
        await voz.enviar_audio(websocket, stream_sid, voz.sintetizar_streaming(respuesta))
    except WebSocketDisconnect:
        raise
    except Exception:
        logger.exception("canal voz: fallo el TTS")


async def _saludar(websocket: WebSocket, stream_sid: str, telefono: str) -> None:
    """La IA habla primero apenas conecta la llamada, en vez de esperar en
    silencio a que el ciudadano diga algo -- es lo que un ciudadano espera de
    una línea telefónica real."""
    async with async_session_factory() as db:
        saludo = await voz.saludo_inicial(db, telefono)

    try:
        await voz.enviar_audio(websocket, stream_sid, voz.sintetizar_streaming(saludo))
    except WebSocketDisconnect:
        raise
    except Exception:
        logger.exception("canal voz: fallo el saludo inicial")


@router.websocket("/voz/stream")
async def voz_stream(websocket: WebSocket) -> None:
    """Media Stream de una llamada en curso: recibe el audio del ciudadano
    chunk a chunk, detecta turnos por energía (`voz.DetectorDeTurno`), y por
    cada turno corre el ciclo completo devolviendo la respuesta hablada por
    la misma conexión."""
    await websocket.accept()

    stream_sid: str | None = None
    telefono: str | None = None
    detector = voz.DetectorDeTurno()

    try:
        while True:
            mensaje = await websocket.receive_json()
            evento = mensaje.get("event")
            logger.info("canal voz: evento recibido=%s", evento)

            if evento == "start":
                datos_inicio = mensaje["start"]
                stream_sid = datos_inicio["streamSid"]
                telefono = (datos_inicio.get("customParameters") or {}).get("telefono")
                logger.info("canal voz: llamada iniciada stream_sid=%s", stream_sid)
                if telefono:
                    await _saludar(websocket, stream_sid, telefono)

            elif evento == "media":
                chunk = base64.b64decode(mensaje["media"]["payload"])
                if detector.agregar_chunk(chunk):
                    audio_turno = detector.tomar_turno()
                    await _procesar_turno_de_voz(websocket, stream_sid, telefono, audio_turno)

            elif evento == "stop":
                logger.info("canal voz: llamada finalizada stream_sid=%s", stream_sid)
                break

    except WebSocketDisconnect:
        logger.info("canal voz: WebSocket desconectado stream_sid=%s", stream_sid)
    except Exception:
        logger.exception("canal voz: error inesperado en el stream stream_sid=%s", stream_sid)
