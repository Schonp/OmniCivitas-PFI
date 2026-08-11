from typing import Literal, Optional, TypedDict


class AgentState(TypedDict):
    mensaje: str
    canal: Literal["whatsapp", "email", "voz", "web"]
    identificador: str
    ciudadano_id: Optional[str]
    caso_id: Optional[str]
    historial: list[dict]
    conocimiento: list[str]
    intencion: Optional[str]
    entidades: dict
    confianza: float
    resultado_ejecucion: Optional[dict]
    requiere_escalado: bool
    motivo_escalado: Optional[str]
    respuesta: Optional[str]
