"""Esquema de un ejemplo de entrenamiento para el fine-tuning de intake/ejecutor.

Mismo formato que describe la tesis (chapter04.tex, "Entrenamiento del modelo
de lenguaje"): una instrucción de un turno, la clasificación esperada y,
cuando corresponde, la llamada a herramienta y la respuesta al ciudadano.
"""
from typing import Literal, Optional

from pydantic import BaseModel

Intencion = Literal["consulta", "reclamo", "reserva", "tramite", "otro"]

# Nombres y parámetros tal como los expone `construir_tools` en
# app/agents/ejecutor.py. Nunca incluir caso_id/ciudadano_id: esos los cierra
# el ejecutor por clausura, el LLM no los ve (Restricción Crítica 2b del
# skill de proyecto — ver DEVLOG.md).
NombreHerramienta = Literal["crear_reclamo", "crear_reserva", "consultar_estado_caso"]


class LlamadaHerramienta(BaseModel):
    nombre: NombreHerramienta
    parametros: dict


class EjemploEntrenamiento(BaseModel):
    instruccion: str
    intencion: Intencion
    confianza: float
    llamada_herramienta: Optional[LlamadaHerramienta] = None
    respuesta: Optional[str] = None
    fuente: Literal["massive", "multi3nlu", "manual", "manual_generado"]
