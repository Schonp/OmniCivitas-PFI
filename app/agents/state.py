from typing import Literal, Optional, TypedDict


class AgentState(TypedDict):
    mensaje: str
    canal: Literal["whatsapp", "email", "voz"]
    identificador: str
    ciudadano_id: Optional[str]
    identificado: bool
    caso_id: Optional[str]
    en_manos_humanas: bool
    historial: list[dict]
    conocimiento: list[str]
    # Pautas generales del organismo: entran al ejecutor en todos los turnos.
    pautas: list[str]
    intencion: Optional[str]
    continua_caso_abierto: bool
    entidades: dict
    confianza: float
    resultado_ejecucion: Optional[dict]
    requiere_escalado: bool
    motivo_escalado: Optional[str]
    respuesta: Optional[str]
    # No se define de qué se trata todavía: no se abre caso.
    tipo_sin_definir: bool
    # Qué tipo eligió recién del menú, si esto viene de ahí. El mensaje real es
    # un número pelado ("1", "2", "3"): sin esto, ejecutor y escalado lo reciben
    # sin saber que significa algo, y le preguntan al ciudadano qué quiso decir
    # con "2". Se resetea cada turno (a diferencia de `vueltas_sin_definir` y
    # `ofertas`, no necesita sobrevivir entre mensajes).
    origen_menu: Optional[str]
    # Qué se le ofreció numerado en el último menú. Como `vueltas_sin_definir`,
    # NO se reinicia en cada mensaje: sin esto un "4" llega sin nada con qué
    # resolverse, porque el saludo que mostró la lista no abre caso y no queda
    # en el historial.
    ofertas: list[dict]
    # El caso que el ciudadano eligió por número.
    caso_elegido: Optional[str]
    # Cuántas veces seguidas se repreguntó sin entender. A diferencia del resto
    # del estado, esta clave NO se reinicia en cada mensaje: sobrevive en el
    # checkpointer para poder poner un tope. Ver `_estado_inicial`.
    vueltas_sin_definir: int
