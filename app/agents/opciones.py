"""Nodo de opciones: el ciudadano escribió, pero no se entiende qué necesita.

Antes esto era una derivación directa: intención "otro" o confianza por debajo
del umbral mandaban el caso a un operador. Molestar a una persona porque el
clasificador no entendió un mensaje ambiguo es caro y, sobre todo, innecesario:
lo que haría cualquiera atendiendo es preguntar.

Dos reglas lo mantienen honesto:

- **No abre caso.** Mientras no esté claro de qué se trata, etiquetarlo es
  inventar: así se creaban casos de tipo "consulta" que en realidad eran
  reclamos, porque "consulta" es el valor al que cae lo que no encaja.
- **Tiene tope.** Después de `MAX_VUELTAS_SIN_DEFINIR` intentos el router deriva
  igual. Preguntar dos veces es atender; preguntar cinco es un laberinto, y el
  ciudadano que no logra explicarse con el agente es exactamente el que
  necesita una persona.
"""

import logging

from app.agents.state import AgentState

logger = logging.getLogger(__name__)

RESPUESTA_OPCIONES = (
    "Perdón, no me quedó claro qué necesita. ¿Me lo confirma?\n\n"
    "1. Reclamo: algo que no está funcionando y hay que resolver.\n\n"
    "2. Consulta: información sobre requisitos, horarios o plazos.\n\n"
    "3. Trámite: iniciar una gestión o sacar un turno.\n\n"
    "Con una línea contándome qué pasó ya me alcanza para encaminarlo."
)


# Por voz no se lee una lista numerada: se nombran las opciones en una frase.
RESPUESTA_OPCIONES_VOZ = (
    "Perdón, no me quedó claro qué necesita. ¿Es un reclamo, una consulta o un turno? "
    "Con una frase contándome qué pasa me alcanza."
)
RESPUESTA_ALGO_NUEVO = "Claro. Cuénteme qué necesita: un reclamo, una consulta o un turno."


async def nodo_opciones(state: AgentState) -> dict:
    if state.get("pide_algo_nuevo"):
        # Pidió empezar algo nuevo: no es que no se le entendió.
        return {
            "respuesta": RESPUESTA_ALGO_NUEVO,
            "caso_id": None,
            "tipo_sin_definir": True,
            "requiere_escalado": False,
        }
    vueltas = state.get("vueltas_sin_definir", 0) + 1
    logger.debug("opciones: se repregunta sin abrir caso (vuelta %s)", vueltas)
    return {
        "respuesta": RESPUESTA_OPCIONES_VOZ if state.get("canal") == "voz" else RESPUESTA_OPCIONES,
        # Sin tipo no hay caso: etiquetarlo ahora sería adivinar.
        "caso_id": None,
        "tipo_sin_definir": True,
        "requiere_escalado": False,
        "vueltas_sin_definir": vueltas,
    }
