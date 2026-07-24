from fastapi import FastAPI

from app.api import health

app = FastAPI(title="OmniCivitas")

app.include_router(health.router)
