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
import re
import wave
from collections.abc import AsyncIterator
from xml.sax.saxutils import escape

import httpx
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.agents.aviso_ia import es_primer_contacto
from app.agents.eleccion import armar_ofertas, armar_ofertas_voz
from app.agents.graph import procesar_mensaje
from app.agents.saludo import MAX_CASOS_VOZ, armar_saludo
from app.agents.state import AgentState
from app.channels.whatsapp import normalizar_telefono
from app.core.config import settings
from app.db.crud.casos import listar_casos_activos_de_ciudadano
from app.db.crud.ciudadanos import (
    alta_por_contacto,
    documento_provisorio,
    obtener_ciudadano_por_telefono,
)
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.models import Canal, Ciudadano, EstadoCaso
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
# ~1,2 s de silencio sostenido = el ciudadano terminó. Con 500 ms, y todavía
# con 800 ms, una pausa breve a mitad de frase ("es un reclamo... hay un auto
# mal estacionado") cortaba el turno: el agente contestaba medio mensaje y lo
# que el ciudadano seguía diciendo se perdía mientras se procesaba.
CHUNKS_SILENCIO_FIN_TURNO = 60
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
    return await alta_por_contacto(
        db,
        CiudadanoCreate(
            documento=documento_provisorio(telefono),
            nombre=NOMBRE_POR_DEFECTO,
            telefono=telefono,
        ),
    )


async def recibir_turno(
    db: AsyncSession, *, telefono: str, mensaje: str, ofertas: list[dict] | None = None
) -> AgentState:
    """Punto de entrada del canal para un turno ya transcripto: asegura el
    ciudadano y corre el grafo. Equivalente a `whatsapp.recibir_mensaje`, pero
    un turno de voz ya llega transcripto por `transcribir()`, no como texto
    tecleado directamente."""
    numero = normalizar_telefono(telefono)
    await identificar_ciudadano(db, numero)
    logger.debug("canal voz: turno entrante")
    return await procesar_mensaje(
        db, mensaje=mensaje, canal=CANAL, identificador=numero, ofertas=ofertas
    )


async def saludo_inicial(db: AsyncSession, telefono: str) -> str:
    """Solo el texto del saludo (ver `saludo_inicial_con_ofertas`)."""
    texto, _ofertas = await saludo_inicial_con_ofertas(db, telefono)
    return texto


async def saludo_inicial_con_ofertas(db: AsyncSession, telefono: str) -> tuple[str, list[dict]]:
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
    # Solo los casos abiertos: uno en progreso o escalado ya lo está atendiendo
    # una persona, y por teléfono no hay operadores que lo puedan retomar.
    # Ofrecerlo era nombrarle al vecino un caso que el agente no puede seguir.
    casos_en_curso = [
        caso
        for caso in await listar_casos_activos_de_ciudadano(db, ciudadano.id)
        if caso.estado == EstadoCaso.abierto
    ]
    primeros = await primeros_mensajes_de_casos(db, [caso.id for caso in casos_en_curso])
    ofertas = armar_ofertas(casos_en_curso)
    primer_contacto = await es_primer_contacto(db, ciudadano.id)
    texto = armar_saludo(
        casos_en_curso, primeros, ofertas, canal=Canal.voz, primer_contacto=primer_contacto
    )
    # Lo que se nombró, en el orden en que se nombró: la respuesta ("el dos")
    # se resuelve contra esto en el primer turno.
    return texto, armar_ofertas_voz(casos_en_curso[:MAX_CASOS_VOZ])


# --- ASR / TTS (servicio propio, ver voz_asr_tts/) ---------------------------


# --- DNI dictado -------------------------------------------------------------

_DIGITOS_EN_PALABRAS = {
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}
_PALABRA_DIGITO = "(?:" + "|".join(_DIGITOS_EN_PALABRAS) + ")"
_SEPARADOR_DICTADO = r"[\s,.\-]+"
# Tres o más dígitos dichos uno por uno y que quedaron en palabras.
_CORRIDA_DE_PALABRAS = re.compile(
    rf"\b{_PALABRA_DIGITO}(?:{_SEPARADOR_DICTADO}{_PALABRA_DIGITO}){{2,}}\b", re.IGNORECASE
)
# Grupos de números separados solo por espacios, puntos, comas o guiones.
_CORRIDA_DE_NUMEROS = re.compile(rf"(?<!\d)\d{{1,4}}(?:{_SEPARADOR_DICTADO}\d{{1,4}})+(?!\d)")
LARGOS_DE_DNI = (7, 8)


def unir_dni_dictado(texto: str) -> str:
    """Junta un DNI dictado de a dígitos o de a pares en un solo número.

    Whisper casi siempre pasa los dígitos dictados a números, pero agrupados a
    su manera según las pausas: "cuatro, tres, cuatro, cero, tres, dos, cuatro,
    dos" llega como "3012-3456", y de a pares también. Sin unirlos, la regla
    que lee el DNI (`agents/identidad.py`) no lo encuentra y el agente lo
    vuelve a pedir. Solo se unen los grupos que suman 7 u 8 dígitos, el largo
    de un DNI: una dirección ("Guatemala 4100"), un horario o un teléfono
    completo quedan como estaban.
    """

    def palabras_a_digitos(coincidencia: re.Match) -> str:
        palabras = re.split(_SEPARADOR_DICTADO, coincidencia.group(0).strip())
        return "".join(_DIGITOS_EN_PALABRAS[palabra.lower()] for palabra in palabras)

    def unir(coincidencia: re.Match) -> str:
        digitos = re.sub(r"\D", "", coincidencia.group(0))
        return digitos if len(digitos) in LARGOS_DE_DNI else coincidencia.group(0)

    texto = _CORRIDA_DE_PALABRAS.sub(palabras_a_digitos, texto)
    return _CORRIDA_DE_NUMEROS.sub(unir, texto)


# --- Apellido deletreado ------------------------------------------------------

_LETRA = r"[A-ZÑ]"
_NO_LETRA_ANTES = r"(?<![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"
_NO_LETRA_DESPUES = r"(?![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"
# Whisper transcribe un deletreo ("ese, ce, hache, o, ene") como letras
# sueltas en mayúscula: "S-C-H-O-N". Tres o más, para no confundir una "Y" o una
# "A" sueltas con un deletreo.
_DELETREO = rf"{_NO_LETRA_ANTES}{_LETRA}(?:[\s,.\-]+{_LETRA}){{2,}}{_NO_LETRA_DESPUES}"
# "Pedro Schón, se escribe S-C-H-O-N": lo deletreado corrige lo que se entendió.
_PALABRA_Y_SU_DELETREO = re.compile(
    rf"[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]+,?\s+(?:que\s+)?se\s+(?:escribe|deletrea)\s+({_DELETREO})"
)
# "Pedro, S-C-H-O-N": el deletreo ocupa el lugar del apellido.
_DELETREO_SUELTO = re.compile(rf",?\s*({_DELETREO})")
# Siglas que alguien podría deletrear: se escriben juntas, en mayúscula, y no
# se toman como apellido.
_SIGLAS = {"DNI", "CUIT", "CUIL", "ABL", "SUBE", "VTV", "AFIP", "ARBA", "ANSES", "ARCA"}


def unir_apellido_deletreado(texto: str) -> str:
    """Convierte un apellido deletreado letra por letra en la palabra escrita.

    Un apellido poco común casi nunca se transcribe bien de oído, y deletrearlo
    es lo que cualquiera hace por teléfono. La regla que lee el nombre
    (`agents/identidad.py`) espera palabras con mayúscula inicial, así que sin
    esto el apellido deletreado se perdía y el caso quedaba solo con el nombre.
    """

    def letras(deletreo: str) -> str:
        return re.sub(r"[^A-ZÑ]", "", deletreo)

    def reemplazar_palabra(coincidencia: re.Match) -> str:
        if letras(coincidencia.group(1)) in _SIGLAS:
            return coincidencia.group(0)
        return letras(coincidencia.group(1)).capitalize()

    def reemplazar_suelto(coincidencia: re.Match) -> str:
        palabra = letras(coincidencia.group(1))
        if palabra in _SIGLAS:
            # La coma y el espacio de adelante quedan como estaban.
            return coincidencia.group(0).replace(coincidencia.group(1), palabra)
        return f" {palabra.capitalize()}"

    texto = _PALABRA_Y_SU_DELETREO.sub(reemplazar_palabra, texto)
    return _DELETREO_SUELTO.sub(reemplazar_suelto, texto).strip()


def normalizar_dictado(texto: str) -> str:
    """Lo que el ciudadano dictó de a partes (DNI, apellido), escrito entero."""
    return unir_apellido_deletreado(unir_dni_dictado(texto))


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
        return normalizar_dictado(respuesta.json()["texto"])


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
