import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import Canal, EstadoCaso, TipoCaso


class CasoCreate(BaseModel):
    ciudadano_id: uuid.UUID
    tipo: TipoCaso
    canal_origen: Canal


MotivoCierre = Literal[
    "resuelto",
    "derivado",
    "sin_respuesta_del_ciudadano",
    "duplicado",
    "fuera_de_alcance",
]
MOTIVOS_CIERRE = get_args(MotivoCierre)


class CasoEstadoUpdate(BaseModel):
    estado: EstadoCaso
    motivo: MotivoCierre | None = None

    @model_validator(mode="after")
    def _cierre_requiere_motivo(self) -> "CasoEstadoUpdate":
        if self.estado == EstadoCaso.cerrado and self.motivo is None:
            raise ValueError("Cerrar un caso requiere tipificar el motivo")
        return self


class CiudadanoResumen(BaseModel):
    """Datos mínimos para que el operador identifique al ciudadano en el panel.
    Sin email ni teléfono: el panel no necesita mostrar datos de contacto."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    documento: str


class OperadorResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str


class CasoTituloUpdate(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)


class CasoAsignacionUpdate(BaseModel):
    operador_asignado_id: uuid.UUID | None = Field(
        default=None, description="null libera el caso."
    )


class RespuestaOperadorCreate(BaseModel):
    contenido: str = Field(min_length=1, max_length=2000)
    interna: bool = Field(
        default=False, description="Nota visible solo para el organismo, nunca para el ciudadano."
    )


class AvisoCasoOut(BaseModel):
    caso: "CasoOut"
    motivo: Literal["derivado", "asignado"]
    momento: datetime


class AvisosOut(BaseModel):
    ahora: datetime = Field(description="Hora del servidor: el `desde` de la próxima consulta.")
    avisos: list[AvisoCasoOut]


class ConteoCasosOut(BaseModel):
    todos: int
    por_estado: dict[str, int]


class CasoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    referencia: str
    ciudadano_id: uuid.UUID
    ciudadano: CiudadanoResumen
    operador_asignado: OperadorResumen | None
    tipo: TipoCaso
    estado: EstadoCaso
    canal_origen: Canal
    canal_actual: Canal
    operador_asignado_id: uuid.UUID | None
    motivo_cierre: str | None
    titulo: str | None = None
    resumen_ia: str | None
    resumen_ia_generado_en: datetime | None
    esperando_desde: datetime | None = Field(
        default=None,
        description="Momento del último mensaje del ciudadano todavía sin respuesta.",
    )
    created_at: datetime
    updated_at: datetime


AvisoCasoOut.model_rebuild()
