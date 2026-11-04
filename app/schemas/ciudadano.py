import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ActorInteraccion, Canal, EstadoCaso, TipoCaso
from app.schemas.caso import OperadorResumen


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


class CiudadanoRectificacion(BaseModel):
    """Campos que el titular puede pedir corregir (RF-14). Solo se tocan los presentes."""

    nombre: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=30)


class UltimoMensajeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    actor: ActorInteraccion
    canal: Canal
    contenido: str
    timestamp: datetime


class CasoEnFichaOut(BaseModel):
    id: uuid.UUID
    referencia: str
    tipo: TipoCaso
    estado: EstadoCaso
    canal_origen: Canal
    canal_actual: Canal
    operador_asignado: OperadorResumen | None
    created_at: datetime
    updated_at: datetime
    mensajes: int
    recorrido: list[Canal]
    puede_abrir: bool = Field(
        description="Si quien mira puede abrir el caso. Si no, la ficha no trae su contenido."
    )
    resumen_ia: str | None = None
    ultimo_mensaje: UltimoMensajeOut | None = None


class FichaCiudadanoOut(BaseModel):
    """Todo lo del vecino en todos los canales, sin datos de contacto."""

    id: uuid.UUID
    nombre: str
    documento: str
    identificado: bool
    canales: list[Canal]
    primer_contacto: datetime | None
    ultimo_contacto: datetime | None
    casos: list[CasoEnFichaOut]
