import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import Canal, EstadoCaso, TipoCaso


class CasoCreate(BaseModel):
    ciudadano_id: uuid.UUID
    tipo: TipoCaso
    canal_origen: Canal


class CasoEstadoUpdate(BaseModel):
    estado: EstadoCaso


class CasoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ciudadano_id: uuid.UUID
    tipo: TipoCaso
    estado: EstadoCaso
    canal_origen: Canal
    canal_actual: Canal
    operador_asignado_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
