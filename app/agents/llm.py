from langchain_anthropic import ChatAnthropic

from app.core.config import settings


def get_llm_intake() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.agente_modelo_intake,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        temperature=0.0,
    )


def get_llm_ejecutor() -> ChatAnthropic:
    # Sin `temperature`: los modelos de la generación de Sonnet 5 en adelante
    # eliminaron los parámetros de sampling y responden 400 si se los manda.
    # El intake sí lo conserva porque Haiku 4.5 todavía lo acepta.
    return ChatAnthropic(
        model=settings.agente_modelo_ejecutor,
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
    )
