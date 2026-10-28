import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.caso import CiudadanoResumen


class ReservaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caso_id: uuid.UUID
    referencia: str
    ciudadano: CiudadanoResumen
    fecha_hora: datetime
    estado: str
    motivo_cancelacion: str | None
    cancelada_en: datetime | None
    recordatorio_enviado_en: datetime | None
    created_at: datetime


class BloqueoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turno_id: uuid.UUID | None
    fecha: date
    motivo: str


class TurnoOut(BaseModel):
    """Una agenda con su grilla y las reservas del rango pedido."""

    id: uuid.UUID
    nombre: str
    descripcion: str
    sede: str | None
    dias_atencion: list[int]
    hora_apertura: str
    hora_cierre: str
    duracion_minutos: int
    cupos_por_horario: int
    anticipacion_maxima_dias: int
    horario: str
    # Del rango pedido: cuántos lugares ofrece la grilla y cuántos están tomados.
    capacidad: int
    ocupados: int
    reservas: list[ReservaOut]
    # Días sin atención dentro del rango pedido (de esta agenda o de todas).
    bloqueos: list[BloqueoOut]


class HorarioOut(BaseModel):
    fecha_hora: datetime
    ocupados: int
    cupos: int
    reservable: bool


class CancelacionIn(BaseModel):
    motivo: str | None = None


class AsistenciaIn(BaseModel):
    estado: Literal["atendida", "ausente"]


class AgendaUpdate(BaseModel):
    """Lo que el supervisor puede ajustar de una agenda. Lo que no viene, no cambia."""

    sede: str | None = Field(default=None, max_length=200)
    dias_atencion: list[int] | None = Field(default=None, min_length=1)
    hora_apertura: time | None = None
    hora_cierre: time | None = None
    duracion_minutos: int | None = Field(default=None, ge=5, le=240)
    cupos_por_horario: int | None = Field(default=None, ge=1, le=50)
    anticipacion_maxima_dias: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def _dias_validos(self) -> "AgendaUpdate":
        if self.dias_atencion is not None and not all(0 <= d <= 6 for d in self.dias_atencion):
            raise ValueError("Los días van de 0 (lunes) a 6 (domingo)")
        return self


class BloqueoIn(BaseModel):
    fecha: date
    motivo: str = Field(min_length=1, max_length=200)
    # Sin agenda, el día queda bloqueado para todas (un feriado).
    turno_id: uuid.UUID | None = None


class BloqueoCreado(BaseModel):
    bloqueo: BloqueoOut
    # Turnos que ya estaban dados ese día: el organismo decide si los cancela.
    afectados: list[ReservaOut]


class ReservaPanelIn(BaseModel):
    """Un turno que carga el operador para quien llamó o se acercó a la sede."""

    documento: str = Field(min_length=6, max_length=20, pattern=r"^\d+$")
    nombre: str | None = Field(default=None, max_length=200)
    fecha_hora: datetime
    canal: Literal["whatsapp", "email", "voz"] = "voz"


class ReprogramacionIn(BaseModel):
    fecha_hora: datetime


class RecordatoriosIn(BaseModel):
    fecha: date | None = None


class RecordatoriosOut(BaseModel):
    dia: date
    total: int
    enviados: int
    no_enviados: list[dict]
