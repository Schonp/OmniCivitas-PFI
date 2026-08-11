import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ActorInteraccion


class AuditoriaOut(BaseModel):
    # El modelo guarda el JSON en `metadata_` porque `metadata` está reservado
    # en SQLAlchemy. Ese detalle interno no tiene por qué salir en la API.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    caso_id: uuid.UUID
    accion: str
    actor: str
    actor_tipo: ActorInteraccion
    timestamp: datetime
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
