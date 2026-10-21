"""Canal de voz sobre Twilio (solo transporte) + ASR/TTS propio.

Cumple el mismo contrato que los demás canales: normaliza al ciudadano y su
identificador, delega en el orquestador y transmite la respuesta. La
continuidad la resuelve el grafo a partir de `canal + identificador`, igual
que WhatsApp -- acá el identificador también es el teléfono, por eso
`Canal.voz` ya se resuelve por hash de teléfono en
`contexto.obtener_ciudadano_por_canal` desde que se agregó ese canal al enum.

**Arquitectura distinta a WhatsApp/email.** Esos dos son canales de
petición-respuesta: un webhook por mensaje. Una llamada es una conexión larga:
Twilio abre un único WebSocket bidireccional (Media Streams) por el resto de
la llamada después de que el webhook HTTP de alta devuelve el TwiML que lo
conecta. Toda la conversación corre sobre esa misma conexión, no sobre
webhooks sucesivos -- por eso acá no hay un `recibir_mensaje` por request como
en WhatsApp, sino un detector de turno que acumula audio y dispara el grafo
cuando el ciudadano termina de hablar.

**Detección de turno.** Twilio no hace VAD (reconocimiento de actividad de
voz): manda audio continuo, hable o calle el ciudadano. Acá se detecta "el
ciudadano terminó de hablar" con un umbral de energía simple sobre el PCM de
cada chunk entrante (`DetectorDeTurno`), no un VAD real -- no distingue ruido
de fondo de una voz baja. Es la opción más simple que funciona para un
prototipo; un VAD de verdad (ej. Silero VAD) queda para una iteración
posterior si la calidad no alcanza. Ver DEVLOG.md ("Detección de turno: por
qué energía y no VAD").

**Audio.** Twilio manda/espera mulaw 8kHz mono, sin encabezado de archivo.
Kokoro genera a 24kHz. La conversión usa `audioop` (stdlib, deprecado desde
3.13 pero presente en 3.12 -- si se actualiza Python, migrar a `audioop-lts`,
mismo API) en vez de reimplementar el códec G.711 a mano.
"""

import audioop
import base64
import io
import logging
import wave
from collections.abc import AsyncIterator
from xml.sax.saxutils import escape

import httpx
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.agents.eleccion import armar_ofertas
from app.agents.graph import procesar_mensaje
from app.agents.saludo import armar_saludo
from app.agents.state import AgentState
from app.channels.whatsapp import normalizar_telefono
from app.core.config import settings
from app.db.crud.casos import listar_casos_activos_de_ciudadano
from app.db.crud.ciudadanos import (
    crear_ciudadano,
    documento_provisorio,
    obtener_ciudadano_por_telefono,
)
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.models import Canal, Ciudadano
from app.schemas.ciudadano import CiudadanoCreate

logger = logging.getLogger(__name__)

CANAL = Canal.voz
NOMBRE_POR_DEFECTO = "Ciudadano sin identificar"
TIMEOUT_ASR_TTS = 20.0

SAMPLE_RATE_TWILIO = 8000
SAMPLE_RATE_KOKORO = 24000
ANCHO_MUESTRA_PCM = 2  # 16 bits

# Parámetros del detector de turno por energía. A 8kHz mulaw, Twilio manda un
# chunk cada 20ms (160 bytes mulaw = 160 muestras). Afinados a ojo para una
# demo, no medidos contra audio real todavía -- ver DEVLOG.md.
UMBRAL_ENERGIA_VOZ = 300  # RMS de PCM 16-bit por debajo de esto cuenta como silencio
CHUNKS_SILENCIO_FIN_TURNO = 25  # ~500ms de silencio sostenido = el ciudadano terminó
CHUNKS_MINIMOS_HABLA = 10  # ~200ms de habla mínima antes de considerar que hubo un turno


# --- Entrada: webhook de alta de llamada ------------------------------------


def validar_firma(url: str, parametros: dict[str, str], firma: str | None) -> bool:
    """Valida `X-Twilio-Signature` con el validador oficial de Twilio.

    A diferencia de la firma de Meta (HMAC-SHA256 simple sobre el cuerpo
    crudo, reimplementada en `whatsapp.validar_firma`), el algoritmo de
    Twilio tiene más matices -- orden exacto de concatenación de parámetros,
    casos de URL-encoding -- y la documentación de Twilio dice explícitamente
    "no implementes tu propia validación de firma". Por eso acá sí se usa el
    paquete oficial (`twilio`), aunque sea la única pieza de ese SDK que se
    usa en todo el proyecto. En desarrollo, si no hay auth token configurado,
    se deja pasar para poder probar sin credenciales.
    """
    if not settings.twilio_auth_token:
        logger.warning("canal voz: sin TWILIO_AUTH_TOKEN, no se valida la firma")
        return settings.debug
    if not firma:
        return False
    validador = RequestValidator(settings.twilio_auth_token)
    return validador.validate(url, parametros, firma)


def twiml_conectar_stream(telefono: str) -> str:
    """TwiML que conecta la llamada al WebSocket de Media Streams.

    El teléfono del llamante viaja como `<Parameter>` propio: Twilio no lo
    manda en los mensajes de Media Streams (`start.customParameters` sólo
    trae lo que se declare acá), así que sin esto el WebSocket no tendría
    forma de saber quién está llamando.
    """
    url = escape(settings.voz_websocket_url)
    valor_telefono = escape(telefono)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Connect><Stream url="{url}">'
        f'<Parameter name="telefono" value="{valor_telefono}" />'
        "</Stream></Connect></Response>"
    )


# --- Ciudadano y orquestador -------------------------------------------------


async def identificar_ciudadano(db: AsyncSession, telefono: str) -> Ciudadano:
    """Busca por teléfono y, si es el primer contacto, da de alta al ciudadano.

    Mismo criterio que `whatsapp.identificar_ciudadano`: se resuelve por
    teléfono, así que un ciudadano que ya escribió por WhatsApp se identifica
    igual si ahora llama por voz (y viceversa)."""
    ciudadano = await obtener_ciudadano_por_telefono(db, telefono)
    if ciudadano is not None:
        return ciudadano

    logger.info("canal voz: alta de ciudadano por primer contacto")
    return await crear_ciudadano(
        db,
        CiudadanoCreate(
            documento=documento_provisorio(telefono),
            nombre=NOMBRE_POR_DEFECTO,
            telefono=telefono,
        ),
    )


async def recibir_turno(db: AsyncSession, *, telefono: str, mensaje: str) -> AgentState:
    """Punto de entrada del canal para un turno ya transcripto: asegura el
    ciudadano y corre el grafo. Equivalente a `whatsapp.recibir_mensaje`, pero
    un turno de voz ya llega transcripto por `transcribir()`, no como texto
    tecleado directamente."""
    numero = normalizar_telefono(telefono)
    await identificar_ciudadano(db, numero)
    logger.debug("canal voz: turno entrante")
    return await procesar_mensaje(db, mensaje=mensaje, canal=CANAL, identificador=numero)


async def saludo_inicial(db: AsyncSession, telefono: str) -> str:
    """El saludo con el que arranca la llamada, antes de que el ciudadano diga
    una palabra.

    En WhatsApp/email el saludo lo dispara un "hola" escrito que el grafo
    clasifica como intención "saludo" (`nodo_saludo`); en una llamada no hay
    ningún mensaje del ciudadano todavía con qué clasificar nada -- Twilio
    conecta el stream y de ahí en más el silencio es del ciudadano, no de la
    IA. Por eso acá se arma el mismo saludo directo (mismos datos: ciudadano,
    casos en curso) en vez de pasar por el grafo con un mensaje inventado."""
    numero = normalizar_telefono(telefono)
    ciudadano = await identificar_ciudadano(db, numero)
    casos_en_curso = await listar_casos_activos_de_ciudadano(db, ciudadano.id)
    primeros = await primeros_mensajes_de_casos(db, [caso.id for caso in casos_en_curso])
    ofertas = armar_ofertas(casos_en_curso)
    return armar_saludo(casos_en_curso, primeros, ofertas, canal=Canal.voz)


# --- ASR / TTS (servicio propio, ver voz_asr_tts/) ---------------------------


async def transcribir(audio_wav: bytes) -> str:
    """Manda un WAV al servicio de ASR y devuelve el texto. Vacío si no se
    entendió nada (silencio, ruido) -- quien llama decide si eso amerita un
    turno o se descarta."""
    async with httpx.AsyncClient(timeout=TIMEOUT_ASR_TTS) as cliente:
        respuesta = await cliente.post(
            f"{settings.voz_asr_tts_url}/transcribir",
            files={"audio": ("audio.wav", audio_wav, "audio/wav")},
        )
        respuesta.raise_for_status()
        return respuesta.json()["texto"]


async def sintetizar_streaming(texto: str) -> AsyncIterator[bytes]:
    """Manda texto al servicio de TTS y devuelve el audio (PCM16 mono 24kHz,
    el sample rate nativo de Kokoro) a medida que se va sintetizando, frase
    por frase, en vez de esperar el texto completo -- `enviar_audio` reenvía
    cada pedazo a Twilio apenas llega, así la respuesta empieza a escucharse
    en unos segundos en vez de esperar toda la síntesis (ver
    voz_asr_tts/DEVLOG.md, "Streaming de TTS")."""
    cliente = httpx.AsyncClient(timeout=TIMEOUT_ASR_TTS)
    try:
        async with cliente.stream(
            "POST", f"{settings.voz_asr_tts_url}/sintetizar", json={"texto": texto}
        ) as respuesta:
            respuesta.raise_for_status()
            async for chunk in respuesta.aiter_bytes():
                yield chunk
    finally:
        await cliente.aclose()


# --- Conversión de audio ------------------------------------------------


def mulaw_a_wav(mulaw: bytes, sample_rate: int = SAMPLE_RATE_TWILIO) -> bytes:
    """mulaw crudo (como lo manda Twilio) -> WAV PCM 16-bit, para que el
    servicio de ASR lo reciba en un formato que PyAV decodifica sin ambigüedad
    (mulaw crudo sin encabezado no alcanza para que PyAV sepa el formato)."""
    pcm = audioop.ulaw2lin(mulaw, ANCHO_MUESTRA_PCM)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(ANCHO_MUESTRA_PCM)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


BYTES_POR_CHUNK_MULAW = int(SAMPLE_RATE_TWILIO * 20 / 1000)  # 20ms, 1 byte/muestra en mulaw


# --- Detector de turno por energía ------------------------------------------


class DetectorDeTurno:
    """Acumula chunks mulaw entrantes de una llamada y avisa cuándo el
    ciudadano terminó de hablar (silencio sostenido después de haber hablado).
    Una instancia por llamada -- el WebSocket handler crea una por conexión."""

    def __init__(self) -> None:
        self._buffer_mulaw = bytearray()
        self._chunks_silencio = 0
        self._chunks_habla = 0

    def agregar_chunk(self, mulaw: bytes) -> bool:
        """Devuelve True si con este chunk se completó un turno (hubo habla y
        después silencio sostenido). El buffer acumulado se recupera con
        `tomar_turno()` y se resetea ahí, no acá."""
        pcm = audioop.ulaw2lin(mulaw, ANCHO_MUESTRA_PCM)
        energia = audioop.rms(pcm, ANCHO_MUESTRA_PCM)

        if energia >= UMBRAL_ENERGIA_VOZ:
            self._buffer_mulaw += mulaw
            self._chunks_habla += 1
            self._chunks_silencio = 0
            return False

        # Silencio: sigue sumando al buffer (el borde de una palabra no debe
        # cortarse justo donde la energía bajó del umbral), pero cuenta aparte.
        if self._chunks_habla > 0:
            self._buffer_mulaw += mulaw
        self._chunks_silencio += 1

        return (
            self._chunks_habla >= CHUNKS_MINIMOS_HABLA
            and self._chunks_silencio >= CHUNKS_SILENCIO_FIN_TURNO
        )

    def tomar_turno(self) -> bytes:
        """Devuelve el audio acumulado del turno y resetea el detector."""
        audio = bytes(self._buffer_mulaw)
        self._buffer_mulaw = bytearray()
        self._chunks_silencio = 0
        self._chunks_habla = 0
        return audio


# --- Envío de audio al WebSocket --------------------------------------------


async def enviar_audio(
    websocket: WebSocket, stream_sid: str, pcm24k_stream: AsyncIterator[bytes]
) -> None:
    """Resamplea un stream de PCM16 24kHz (la salida de `sintetizar_streaming`)
    a mulaw 8kHz y lo manda a Twilio como mensajes `media` de 20ms a medida
    que va llegando -- no espera a que termine toda la síntesis, por eso el
    parámetro es un stream y no un WAV completo. Termina con un `mark` para
    poder confirmar que terminó de reproducirse (relevante para un futuro
    barge-in, no usado todavía).

    El resampler (`audioop.ratecv`) arrastra su estado entre chunks para que
    no se escuchen clicks en los bordes; lo mismo el resto mulaw que no
    llega a completar un chunk de 20ms, que se arrastra al próximo pedazo de
    PCM que llegue en vez de descartarse.

    El stream HTTP tampoco respeta los límites de 2 bytes/muestra con que
    `sintetizar_streaming` yieldea cada pedazo -- `aiter_bytes()` corta en
    cualquier punto del lado del transporte, no en los bordes de muestra, y
    `audioop.ratecv` revienta (`not a whole number of frames`) si le llega un
    largo impar. Por eso también se arrastra el byte suelto de *entrada*
    entre vueltas, igual que el resto mulaw de salida."""
    estado_resample = None
    sobrante_entrada = b""
    sobrante_mulaw = b""

    async for pedazo in pcm24k_stream:
        pcm24k = sobrante_entrada + pedazo
        resto = len(pcm24k) % ANCHO_MUESTRA_PCM
        sobrante_entrada = pcm24k[len(pcm24k) - resto :] if resto else b""
        if resto:
            pcm24k = pcm24k[: len(pcm24k) - resto]
        if not pcm24k:
            continue

        pcm8k, estado_resample = audioop.ratecv(
            pcm24k, ANCHO_MUESTRA_PCM, 1, SAMPLE_RATE_KOKORO, SAMPLE_RATE_TWILIO, estado_resample
        )
        mulaw = sobrante_mulaw + audioop.lin2ulaw(pcm8k, ANCHO_MUESTRA_PCM)

        n_completos = len(mulaw) // BYTES_POR_CHUNK_MULAW
        for i in range(n_completos):
            chunk = mulaw[i * BYTES_POR_CHUNK_MULAW : (i + 1) * BYTES_POR_CHUNK_MULAW]
            await websocket.send_json(
                {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
        sobrante_mulaw = mulaw[n_completos * BYTES_POR_CHUNK_MULAW :]

    if sobrante_mulaw:
        await websocket.send_json(
            {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(sobrante_mulaw).decode("ascii")},
            }
        )

    await websocket.send_json(
        {
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": "fin_respuesta"},
        }
    )
