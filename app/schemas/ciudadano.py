import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CiudadanoCreate(BaseModel):
    documento: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=200)
    email: str | None = None
    telefono: str | None = None


class CiudadanoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    documento: str
    nombre: str
    email: str | None
    telefono: str | None
    created_at: datetime
