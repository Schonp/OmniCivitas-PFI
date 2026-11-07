"""Servicio propio de ASR/TTS (faster-whisper + Kokoro), separado del proceso
de la API principal -- mismo patrón que el LLM, que corre aparte vía Ollama en
vez de cargarse adentro del proceso de FastAPI (ver app/agents/llm.py).

Expone dos endpoints que usa app/channels/voz.py:
- POST /transcribir: recibe audio, devuelve el texto (ASR).
- POST /sintetizar: recibe texto, devuelve un stream de audio PCM16 24kHz
  crudo, oración por oración (TTS).

Uso: .venv/Scripts/python.exe -m uvicorn servidor:app --port 8001
"""
import glob
import io
import logging
import os
import re
import sys
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager


def _registrar_dlls_cuda() -> None:
    """Hace visibles las DLLs de CUDA que instalan los paquetes nvidia-*-cu12
    de pip (cuBLAS, cuDNN). Quedan en site-packages/nvidia/*/bin, fuera del
    PATH, y ctranslate2 las busca recién en la primera transcripción: sin
    esto falla con "cublas64_12.dll is not found". Tiene que correr antes de
    importar faster_whisper."""
    for carpeta in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.environ["PATH"] = carpeta + os.pathsep + os.environ["PATH"]
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(carpeta)


_registrar_dlls_cuda()

import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from kokoro import KPipeline  # noqa: E402
from pydantic import BaseModel  # noqa: E402

logger = logging.getLogger(__name__)

# En GPU, large-v3-turbo: bastante más preciso que "small" con audio telefónico
# (8 kHz) y, aun así, ~0,7 s por turno contra ~2,6 s de "small" en CPU. En int8
# ocupa ~1 GB de VRAM, que entra al lado del LLM en una placa de 8 GB.
# Si la GPU no está disponible o se queda sin memoria, se cae a "small" en CPU:
# la llamada es más lenta y menos precisa, pero no se queda sin voz.
MODELO_WHISPER_GPU = os.environ.get("WHISPER_MODELO", "large-v3-turbo")
MODELO_WHISPER_CPU = "small"

# Vocabulario del dominio para Whisper: ante un audio dudoso, inclina la
# transcripción hacia estas palabras ("pozo" y no "pulso"). Es contexto, no una
# lista cerrada: el ciudadano puede decir cualquier otra cosa.
CONTEXTO_WHISPER = (
    "Llamada a la línea de atención ciudadana del municipio. Reclamos por pozos, "
    "baches, veredas rotas, luminarias quemadas, basura y árboles caídos. "
    "Consultas, trámites y turnos. Nombre y DNI del vecino, calle y altura."
)
# Kokoro solo tiene 3 voces en español: ef_dora (femenina, única opción) y dos
# masculinas (em_alex, em_santa) -- ver DEVLOG.md ("Voces de Kokoro en español").
VOZ_KOKORO = "ef_dora"
SAMPLE_RATE_KOKORO = 24000

_whisper: WhisperModel | None = None
_whisper_descripcion = ""
_kokoro: KPipeline | None = None


def _cargar_whisper() -> tuple[WhisperModel, str]:
    """Whisper en GPU si se puede; si no, el de CPU. La prueba con un segundo
    de silencio es necesaria: las DLLs de CUDA faltantes o la falta de VRAM
    recién aparecen al transcribir, no al cargar el modelo."""
    try:
        modelo = WhisperModel(MODELO_WHISPER_GPU, device="cuda", compute_type="int8_float16")
        list(modelo.transcribe(np.zeros(16000, dtype=np.float32), language="es")[0])
        return modelo, f"{MODELO_WHISPER_GPU} en GPU"
    except Exception:  # noqa: BLE001 -- cualquier falla de GPU cae al plan B
        logger.exception("Whisper no pudo correr en GPU: se usa %s en CPU", MODELO_WHISPER_CPU)
        modelo = WhisperModel(MODELO_WHISPER_CPU, device="cpu", compute_type="int8")
        return modelo, f"{MODELO_WHISPER_CPU} en CPU (respaldo)"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _whisper, _whisper_descripcion, _kokoro
    logger.info("Cargando faster-whisper y Kokoro...")
    _whisper, _whisper_descripcion = _cargar_whisper()
    _kokoro = KPipeline(lang_code="e")
    logger.info("ASR/TTS listos. Whisper: %s", _whisper_descripcion)
    yield


app = FastAPI(title="OmniCivitas - ASR/TTS", lifespan=lifespan)


class TextoEntrada(BaseModel):
    texto: str


class TranscripcionSalida(BaseModel):
    texto: str
    idioma: str
    confianza_idioma: float


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "whisper_listo": _whisper is not None,
        "whisper": _whisper_descripcion,
        "kokoro_listo": _kokoro is not None,
    }


@app.post("/transcribir", response_model=TranscripcionSalida)
async def transcribir(audio: UploadFile) -> TranscripcionSalida:
    """Recibe un archivo de audio (cualquier formato que decodifique PyAV:
    wav, mp3, etc.) y devuelve el texto transcripto. El canal de voz le pasa
    acá el audio ya decodificado de mulaw 8kHz a un WAV, antes de llamar."""
    if _whisper is None:
        raise HTTPException(status_code=503, detail="El modelo de ASR todavía no está listo")

    contenido = await audio.read()
    if not contenido:
        raise HTTPException(status_code=422, detail="Audio vacío")

    segmentos, info = _whisper.transcribe(
        io.BytesIO(contenido),
        language="es",
        beam_size=5,
        initial_prompt=CONTEXTO_WHISPER,
        # Descarta los tramos sin voz antes de transcribir: con un contexto
        # cargado, Whisper tiende a "inventar" texto sobre el ruido de línea.
        vad_filter=True,
    )
    texto = " ".join(segmento.text.strip() for segmento in segmentos).strip()
    return TranscripcionSalida(
        texto=texto,
        idioma=info.language,
        confianza_idioma=info.language_probability,
    )


PATRON_ORACIONES = re.compile(r"(?<=[.?!])\s+")


def _generar_pcm16(texto: str) -> Generator[bytes, None, None]:
    """Sintetiza oración por oración y devuelve cada una en PCM16LE mono
    24kHz crudo, sin encabezado -- el cliente (`app.channels.voz`) ya conoce
    el formato de antemano, así que no hace falta un contenedor WAV por
    chunk.

    Partir el texto a mano es necesario: el chunking interno de Kokoro no es
    por oración sino por una heurística propia que puede agrupar un párrafo
    entero en un solo pedazo -- medido en un párrafo de 75 palabras, el
    primer (y casi único) pedazo de Kokoro tardaba 9.4s, contra 0.9s
    partiendo nosotros por oración antes de llamarlo (ver DEVLOG.md,
    "Streaming de TTS"). Sin este split, el streaming del lado de la
    respuesta HTTP no gana nada: igual hay que esperar a que Kokoro termine
    su único pedazo gigante.

    Generador sincrónico: Starlette lo corre en threadpool solo, no bloquea
    el loop del proceso."""
    oraciones = [o.strip() for o in PATRON_ORACIONES.split(texto) if o.strip()]
    for oracion in oraciones:
        for _, _, audio in _kokoro(oracion, voice=VOZ_KOKORO, speed=1):
            pcm = np.clip(audio.numpy(), -1.0, 1.0)
            yield (pcm * 32767).astype(np.int16).tobytes()


@app.post("/sintetizar")
async def sintetizar(entrada: TextoEntrada) -> StreamingResponse:
    """Recibe texto y devuelve un stream de PCM16LE mono 24kHz (el sample
    rate nativo de Kokoro) a medida que se va sintetizando, frase por frase,
    en vez de esperar el texto completo -- la primera frase está lista en
    unos segundos en vez de esperar toda la síntesis (ver DEVLOG.md,
    "Streaming de TTS"). El canal de voz reconvierte cada pedazo al formato
    que espera Twilio (mulaw 8kHz) a medida que llega."""
    if _kokoro is None:
        raise HTTPException(status_code=503, detail="El modelo de TTS todavía no está listo")

    if not entrada.texto.strip():
        raise HTTPException(status_code=422, detail="Texto vacío")

    return StreamingResponse(_generar_pcm16(entrada.texto), media_type="application/octet-stream")
