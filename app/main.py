import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.graph import cerrar_checkpointer, iniciar_checkpointer
from app.api import agente, auth, casos, chat, ciudadanos, health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        await iniciar_checkpointer()
    except Exception:
        # El resto de la API (auth, casos, alta de ciudadanos) sigue sirviendo:
        # solo queda fuera el orquestador, que avisa con un error explícito.
        logger.exception("No se pudo inicializar el checkpointer del orquestador")
    yield
    await cerrar_checkpointer()


app = FastAPI(title="OmniCivitas", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(ciudadanos.router)
app.include_router(casos.router)
app.include_router(agente.router)
app.include_router(chat.router)
