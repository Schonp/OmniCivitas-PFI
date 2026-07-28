from fastapi import FastAPI

from app.api import auth, casos, ciudadanos, health

app = FastAPI(title="OmniCivitas")

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(ciudadanos.router)
app.include_router(casos.router)
