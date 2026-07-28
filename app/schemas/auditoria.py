import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ActorInteraccion


class AuditoriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caso_id: uuid.UUID
    accion: str
    actor: str
    actor_tipo: ActorInteraccion
    timestamp: datetime
    metadata_: dict | None
