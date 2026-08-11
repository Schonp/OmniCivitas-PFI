from datetime import date

from pydantic import BaseModel, Field


class CasosDia(BaseModel):
    fecha: date
    casos: int


class MetricasPanel(BaseModel):
    total_casos: int
    por_estado: dict[str, int] = Field(default_factory=dict)
    por_canal: dict[str, int] = Field(default_factory=dict)
    por_tipo: dict[str, int] = Field(default_factory=dict)

    escalados: int
    resueltos_por_ia: int
    tasa_automatizacion: float | None = Field(
        default=None, description="Proporción de casos que nunca requirieron un operador."
    )
    casos_con_cambio_canal: int = Field(
        description="Casos que siguieron en un canal distinto al de origen."
    )
    casos_esperando_respuesta: int = Field(
        description="Casos abiertos cuyo último mensaje del ciudadano sigue sin respuesta."
    )
    casos_demorados: int
    horas_umbral_demora: int
    minutos_primera_respuesta: float | None = None
    confianza_promedio: float | None = None
    casos_por_dia: list[CasosDia] = Field(
        default_factory=list,
        description="Casos creados por día en las últimas dos semanas, con días en cero.",
    )
