# ASR/TTS para el canal de voz (Fase 9)

Servicio propio de reconocimiento de habla (faster-whisper) y síntesis de voz
(Kokoro), separado del proceso de la API principal — mismo patrón que el LLM,
que corre aparte vía Ollama en vez de cargarse adentro del proceso de FastAPI.
Así los tres servicios de IA (LLM, ASR, TTS) quedan simétricos en la
arquitectura, y el servidor de la API no carga modelos de ML pesados en el
mismo proceso que atiende requests HTTP.

Para el relato de decisiones y hallazgos, ver **DEVLOG.md**.

## Setup

```bash
cd voz_asr_tts
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

**Windows**: hace falta `espeak-ng` instalado a nivel de sistema (dependencia
de Kokoro para el fallback de pronunciación). `winget install
eSpeak-NG.eSpeak-NG` y agregar `C:\Program Files\eSpeak NG` al PATH.
**Linux** (infraestructura real): `apt-get install espeak-ng`.

## Uso

```bash
.venv/Scripts/python.exe -m uvicorn servidor:app --port 8001
```

Endpoints:
- `GET /health`
- `POST /transcribir` — multipart, campo `audio` (archivo) → `{"texto", "idioma", "confianza_idioma"}`
- `POST /sintetizar` — JSON `{"texto": "..."}` → WAV (24kHz)

`app/core/config.py` de la app principal apunta acá vía `VOZ_ASR_TTS_URL`
(default `http://localhost:8001`).
