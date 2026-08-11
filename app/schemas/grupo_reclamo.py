import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.caso import CasoOut


class GrupoReclamoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tema: str
    casos: list[CasoOut]
    generado_en: datetime
