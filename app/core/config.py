from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    debug: bool = True

    database_url: str = ""
    test_database_url: str = ""

    redis_url: str = ""

    anthropic_api_key: str = ""
    agente_modelo_intake: str = "claude-haiku-4-5-20251001"
    agente_modelo_ejecutor: str = "claude-sonnet-5"
    agente_umbral_confianza: float = 0.6

    jwt_secret_key: str = ""
    jwt_access_token_expire_hours: int = 8
    jwt_refresh_token_expire_days: int = 7
    chat_session_expire_hours: int = 4

    fernet_key: str = ""
    hash_lookup_key: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    twilio_voice_number: str = ""

    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    whisper_api_key: str = ""

    rate_limit_per_minute: int = 100

    # Origen del panel de operador (Vite dev server). Coma-separado.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origen.strip() for origen in self.cors_origins.split(",") if origen.strip()]


settings = Settings()
