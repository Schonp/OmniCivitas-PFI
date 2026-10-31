import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import cerrar_checkpointer, iniciar_checkpointer
from app.api import (
    agente,
    auth,
    casos,
    ciudadanos,
    conocimiento,
    health,
    metricas,
    reclamos,
    telefono_web,
    turnos,
    usuarios,
    webhooks,
)
from app.core.config import settings

# Sin esto, los logger.info/debug de la app se los come el "handler de último
# recurso" de Python (solo deja pasar WARNING+) porque nada más en el proceso
# llama basicConfig -- uvicorn configura sus propios loggers, no el root.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
    datefmt="%H:%M:%S",
)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto el navegador no puede leer el total de la paginación.
    expose_headers=["X-Total-Count"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(ciudadanos.router)
app.include_router(casos.router)
app.include_router(agente.router)
app.include_router(metricas.router)
app.include_router(usuarios.router)
app.include_router(turnos.router)
app.include_router(conocimiento.router)
app.include_router(reclamos.router)
app.include_router(webhooks.router)
app.include_router(telefono_web.router)
