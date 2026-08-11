import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.caso import CiudadanoResumen


class ReservaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caso_id: uuid.UUID
    ciudadano: CiudadanoResumen
    fecha_hora: datetime
    created_at: datetime


class TurnoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    descripcion: str
    reservas: list[ReservaOut]
