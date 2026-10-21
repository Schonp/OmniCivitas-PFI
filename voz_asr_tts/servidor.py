"""Servicio propio de ASR/TTS (faster-whisper + Kokoro), separado del proceso
de la API principal -- mismo patrón que el LLM, que corre aparte vía Ollama en
vez de cargarse adentro del proceso de FastAPI (ver app/agents/llm.py).

Expone dos endpoints que usa app/channels/voz.py:
- POST /transcribir: recibe audio, devuelve el texto (ASR).
- POST /sintetizar: recibe texto, devuelve un stream de audio PCM16 24kHz
  crudo, oración por oración (TTS).

Uso: .venv/Scripts/python.exe -m uvicorn servidor:app --port 8001
"""
import io
import logging
import re
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from faster_whisper import WhisperModel
from kokoro import KPipeline
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# "small" balancea precisión y latencia para una llamada telefónica; "base" es
# más rápido pero pierde precisión, "medium"/"large" no corren cómodos en CPU.
MODELO_WHISPER = "small"
# Kokoro solo tiene 3 voces en español: ef_dora (femenina, única opción) y dos
# masculinas (em_alex, em_santa) -- ver DEVLOG.md ("Voces de Kokoro en español").
VOZ_KOKORO = "ef_dora"
SAMPLE_RATE_KOKORO = 24000

_whisper: WhisperModel | None = None
_kokoro: KPipeline | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _whisper, _kokoro
    logger.info("Cargando faster-whisper (%s) y Kokoro...", MODELO_WHISPER)
    _whisper = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8")
    _kokoro = KPipeline(lang_code="e")
    logger.info("ASR/TTS listos.")
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
        io.BytesIO(contenido), language="es", beam_size=5
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
