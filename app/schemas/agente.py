import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import Canal


class ClasificacionIntent(BaseModel):
    """Salida estructurada del nodo intake. El LLM nunca devuelve texto libre."""

    intencion: Literal["consulta", "reclamo", "reserva", "tramite", "otro"]
    entidades: dict = Field(default_factory=dict)
    confianza: float = Field(ge=0.0, le=1.0)
    requiere_humano: bool = Field(
        default=False,
        description=(
            "True si el ciudadano pide explícitamente hablar con una persona "
            "o la solicitud involucra datos sensibles (denuncia, documentación legal)."
        ),
    )


class MensajeEntrante(BaseModel):
    mensaje: str = Field(min_length=1)
    canal: Canal
    identificador: str = Field(
        min_length=1,
        description="Teléfono o email con el que el ciudadano escribe por el canal.",
    )


class RespuestaAgente(BaseModel):
    respuesta: str
    caso_id: uuid.UUID | None
    intencion: str | None
    confianza: float
    escalado: bool
