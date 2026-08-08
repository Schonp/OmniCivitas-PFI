import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ActorInteraccion, Canal, EstadoCaso


class InicioSesionChat(BaseModel):
    """Alta/identificación del ciudadano al abrir el chat web. Equivale al número
    de teléfono que identifica al ciudadano en WhatsApp."""

    documento: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _requiere_un_contacto(self) -> "InicioSesionChat":
        if not self.email and not self.telefono:
            raise ValueError("Se requiere email o teléfono para identificar al ciudadano")
        return self


class SesionChat(BaseModel):
    token: str
    ciudadano_id: uuid.UUID
    nombre: str


class MensajeChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)


class RespuestaChat(BaseModel):
    respuesta: str
    caso_id: uuid.UUID | None
    intencion: str | None
    escalado: bool


class InteraccionChat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    actor: ActorInteraccion
    contenido: str
    canal: Canal
    timestamp: datetime


class HistorialChat(BaseModel):
    """Conversación del caso abierto del ciudadano, con las interacciones de
    todos los canales — es lo que hace visible la continuidad cross-canal."""

    caso_id: uuid.UUID | None
    estado: EstadoCaso | None
    interacciones: list[InteraccionChat]
