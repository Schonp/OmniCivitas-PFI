from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    debug: bool = True

    database_url: str = ""
    test_database_url: str = ""

    anthropic_api_key: str = ""
    agente_modelo_intake: str = "claude-haiku-4-5-20251001"
    agente_modelo_ejecutor: str = "claude-sonnet-5"
    agente_umbral_confianza: float = 0.6
    # Minutos de silencio del agente sobre un caso que ya tiene una persona.
    # Recién pasado ese rato vuelve a acusar recibo: si el ciudadano insiste a
    # los dos minutos de que le dijeron que lo van a contactar, repetírselo no
    # aporta nada. Bajalo para las demos, donde no se espera media hora.
    agente_minutos_silencio_derivado: int = 30
    # Cada cuánto se le vuelve a avisar al ciudadano que le contesta una IA. No
    # es por caso: una conversación por WhatsApp puede abrir varios casos si va
    # cambiando de tema, y repetirle el aviso en cada uno es exactamente lo que
    # no queremos.
    agente_horas_aviso_ia: int = 12

    jwt_secret_key: str = ""
    jwt_access_token_expire_hours: int = 8
    jwt_refresh_token_expire_days: int = 7

    fernet_key: str = ""
    hash_lookup_key: str = ""

    # WhatsApp va por la Cloud API de Meta, sin intermediario. Twilio queda
    # solo para el canal de voz de la fase siguiente.
    whatsapp_api_version: str = "v25.0"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    twilio_voice_number: str = ""
    # URL pública wss:// del WebSocket de Media Streams (ver app/channels/voz.py).
    # Twilio exige wss, nunca ws -- no puede ser localhost en producción. Para
    # probar en desarrollo hace falta un túnel (ej. ngrok) y poner acá su URL wss.
    voz_websocket_url: str = ""

    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # Servicio propio de ASR/TTS (faster-whisper + Kokoro), separado del proceso
    # de la API -- mismo patrón que el LLM, que corre aparte vía Ollama y no
    # adentro de este proceso. Ver voz_asr_tts/.
    voz_asr_tts_url: str = "http://localhost:8001"

    rate_limit_per_minute: int = 100

    # Origen del panel de operador (Vite dev server). Coma-separado.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origen.strip() for origen in self.cors_origins.split(",") if origen.strip()]


settings = Settings()
