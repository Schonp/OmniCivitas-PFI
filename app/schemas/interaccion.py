import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ActorInteraccion, Canal


class InteraccionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caso_id: uuid.UUID
    contenido: str
    canal: Canal
    actor: ActorInteraccion
    interna: bool
    timestamp: datetime
