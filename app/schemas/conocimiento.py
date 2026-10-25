import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentoCreate(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    contenido: str = Field(min_length=1, max_length=50_000)
    nombre_archivo: str | None = Field(default=None, max_length=255)
    general: bool = False


class DocumentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    titulo: str
    contenido: str
    nombre_archivo: str | None
    general: bool
    created_at: datetime
