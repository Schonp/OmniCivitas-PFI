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
    return ChatAnthropic(
        model=settings.agente_modelo_ejecutor,
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
        temperature=0.0,
    )
