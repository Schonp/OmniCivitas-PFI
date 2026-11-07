"""Nodo de saludo: abre la conversación ofreciendo por dónde empezar.

Toda conversación empieza saludando, y un saludo no es una solicitud: no hay
nada que gestionar, ningún operador a quien derivar y ningún caso que abrir.
Antes caía en la intención "otro", que el router escala, así que cada persona
que decía "hola" terminaba en la bandeja de un humano.

En vez de contestar "¿en qué puedo ayudarlo?" y esperar a adivinar de qué se
trata, el saludo pone las opciones sobre la mesa. Dos motivos: el ciudadano ve
qué sabe hacer el organismo —que no es obvio— y la clasificación deja de ser
una adivinanza sobre un texto ambiguo, porque la respuesta al menú ya dice de
qué se trata. Si tiene pedidos en curso se los enumera, para que pueda retomar
uno en vez de abrir otro por lo mismo.

La respuesta es fija a propósito: no necesita al modelo, no gasta tokens y
mantiene el mismo tono en todas las conversaciones.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.aviso_ia import AVISO_DATOS_VOZ, RECORDATORIO_DATOS_VOZ
from app.agents.eleccion import armar_ofertas, numero_de_caso
from app.agents.state import AgentState
from app.db.crud.casos import listar_casos_activos_de_ciudadano
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.models import Canal, Caso

logger = logging.getLogger(__name__)

# El aviso de que contesta una IA va acá adentro y no por `aviso_ia`: un saludo
# no abre caso, así que no hay caso donde mirar si el agente ya habló. Y como el
# saludo suele ser el primer mensaje de la conversación, es justo donde el
# ciudadano tiene que enterarse de con qué está hablando.
PRESENTACION = (
    "¡Hola! Soy el asistente virtual de atención ciudadana del organismo: "
    "le responde una inteligencia artificial, no una persona."
)

MENU = (
    "¿Con qué lo puedo ayudar? Puede elegir una opción o contármelo con sus palabras:\n\n"
    "1. Reclamo: algo del espacio público o de un servicio que no está funcionando "
    "(una vereda rota, una luminaria quemada, basura sin recolectar).\n\n"
    "2. Consulta: información sobre requisitos, horarios, plazos o cómo hacer una gestión.\n\n"
    "3. Trámite: iniciar una gestión o sacar un turno de atención."
)

CIERRE = (
    "Si en algún momento prefiere hablar con una persona del equipo, pídamelo y lo derivo."
)

# Se conserva para los tests y para que el intake pueda descartarlo del historial.
RESPUESTA_SALUDO = f"{PRESENTACION}\n\n{MENU}\n\n{CIERRE}"

# Por voz no hay menú: un listado numerado que tiene sentido leído se vuelve
# incómodo hablado, y las opciones de WhatsApp/email asumen que el ciudadano
# puede volver a mirarlas, algo que no pasa en una llamada. En vez de eso se
# abre la conversación con una pregunta abierta, más corta que el texto
# escrito (ver DEVLOG.md de voz_asr_tts, "Diferenciar voz de texto").
#
# Este saludo es lo único que se dice de corrido al empezar cada llamada, así
# que lleva todos los avisos juntos y nada más: que habla una IA, que puede
# pedir una persona y, la primera vez, qué datos se guardan (ver
# `aviso_ia.anteponer_aviso`, que por voz ya no los repite).
PRESENTACION_VOZ = (
    "Hola, le habla el asistente virtual del organismo, una inteligencia artificial. "
    "Si prefiere hablar con una persona, pídamelo cuando quiera."
)
PREGUNTA_ABIERTA_VOZ = "¿En qué lo puedo ayudar?"
RESPUESTA_SALUDO_VOZ = f"{PRESENTACION_VOZ} {PREGUNTA_ABIERTA_VOZ}"
# Una lista larga no se retiene de oído: se nombran los tres más recientes.
MAX_CASOS_VOZ = 3
_NUMERO_HABLADO = {1: "uno", 2: "dos", 3: "tres"}


# Un título largo tapa la referencia, que es lo que el ciudadano tiene que
# decirnos para retomar el caso.
TITULO_MAX = 55


def _recortar(texto: str) -> str:
    """Una línea corta y legible: sin saltos y cortada en una palabra entera."""
    limpio = " ".join(texto.split())
    if len(limpio) <= TITULO_MAX:
        return limpio
    return f"{limpio[:TITULO_MAX].rsplit(' ', 1)[0]}…"


def titulo_de_caso(caso: Caso, primer_mensaje: str | None) -> str:
    """Con qué reconoce el ciudadano su propio caso.

    El título del caso (lo pone el agente al registrar el reclamo o el turno, y
    el supervisor lo puede corregir); si no tiene, el asunto del correo —lo
    escribió él mismo— y si no, sus primeras palabras. La referencia sola no
    alcanza: nadie se acuerda de qué era REC-A6961E4A.
    """
    if caso.titulo:
        return caso.titulo
    if caso.asunto:
        return _recortar(caso.asunto)
    if primer_mensaje:
        return _recortar(primer_mensaje)
    # Un caso abierto por un operador desde el panel puede no tener ninguna.
    return caso.tipo.value.capitalize()


_TIPO_HABLADO = {
    "reclamo": "reclamo por",
    "reserva": "turno de",
    "consulta": "consulta sobre",
    "tramite": "trámite sobre",
}


def _caso_hablado(caso: Caso, primer_mensaje: str | None) -> str:
    """"Reclamo por pozo en Guatemala 4100": el título solo no dice si es un
    reclamo o un turno, y en una llamada no hay etiqueta a la vista."""
    titulo = titulo_de_caso(caso, primer_mensaje).rstrip("…").rstrip(".")
    prefijo = _TIPO_HABLADO.get(caso.tipo.value, "")
    # Si el supervisor ya lo escribió con el tipo adelante, no se repite.
    if not prefijo or titulo.lower().startswith(prefijo.split()[0]):
        return titulo
    return f"{prefijo} {titulo[0].lower() + titulo[1:]}"


def _casos_en_curso_hablados(casos: list[Caso], primeros_mensajes: dict) -> str:
    """"Tiene dos pedidos en curso: uno, reclamo por pozo en Guatemala 4100;
    dos, turno de licencia de conducir. Para seguir con alguno, dígame el
    número; si es algo nuevo, cuénteme qué necesita."
    """
    titulos = [_caso_hablado(caso, primeros_mensajes.get(caso.id)) for caso in casos]
    if len(casos) == 1:
        return (
            f"Tiene un pedido en curso: {titulos[0][0].lower() + titulos[0][1:]}. Para seguir con ese, dígame «uno»; "
            "si es algo nuevo, cuénteme qué necesita."
        )
    lista = "; ".join(f"{_NUMERO_HABLADO[i]}, {t[0].lower() + t[1:]}" for i, t in enumerate(titulos, start=1))
    return (
        f"Tiene {_NUMERO_HABLADO[len(casos)]} pedidos en curso: {lista}. Para seguir con alguno, "
        "dígame el número; si es algo nuevo, cuénteme qué necesita."
    )


def _linea_de_caso(numero: int, caso: Caso, primer_mensaje: str | None) -> str:
    estado = caso.estado.value.replace("_", " ")
    return (
        f"{numero}. {titulo_de_caso(caso, primer_mensaje)}"
        f" ({caso.tipo.value}, {estado} — {caso.referencia})"
    )


def armar_saludo(
    casos_en_curso: list[Caso],
    primeros_mensajes: dict | None = None,
    ofertas: list[dict] | None = None,
    canal: Canal | None = None,
    primer_contacto: bool = False,
) -> str:
    if canal == Canal.voz:
        partes = [PRESENTACION_VOZ]
        partes.append(AVISO_DATOS_VOZ if primer_contacto else RECORDATORIO_DATOS_VOZ)
        if casos_en_curso:
            partes.append(_casos_en_curso_hablados(casos_en_curso[:MAX_CASOS_VOZ], primeros_mensajes or {}))
        else:
            partes.append(PREGUNTA_ABIERTA_VOZ)
        return " ".join(partes)

    primeros_mensajes = primeros_mensajes or {}
    ofertas = ofertas or armar_ofertas(casos_en_curso)
    partes = [PRESENTACION, MENU]
    if casos_en_curso:
        lineas = []
        for caso in casos_en_curso:
            numero = numero_de_caso(ofertas, caso.id)
            if numero is None:
                continue
            lineas.append(_linea_de_caso(numero, caso, primeros_mensajes.get(caso.id)))
        partes.append(
            "O puede seguir uno de sus pedidos en curso:\n\n" + "\n".join(lineas)
        )
    partes.append(CIERRE)
    return "\n\n".join(partes)


async def nodo_saludo(state: AgentState, db: AsyncSession) -> dict:
    ciudadano_id = state.get("ciudadano_id")
    casos_en_curso = (
        await listar_casos_activos_de_ciudadano(db, uuid.UUID(ciudadano_id))
        if ciudadano_id is not None
        else []
    )

    primeros = await primeros_mensajes_de_casos(db, [caso.id for caso in casos_en_curso])
    ofertas = armar_ofertas(casos_en_curso)

    logger.debug("saludo: se responde sin abrir caso (%s en curso)", len(casos_en_curso))
    return {
        "respuesta": armar_saludo(casos_en_curso, primeros, ofertas, canal=Canal(state["canal"])),
        # Sin caso: un saludo no es una unidad de gestión. Si el ciudadano
        # después plantea algo concreto, ahí sí se abre.
        "caso_id": None,
        "requiere_escalado": False,
        # Qué significa cada número cuando conteste. Viaja en el checkpointer
        # porque este saludo no queda registrado en ningún lado.
        "ofertas": ofertas,
        # El menú vuelve a poner el contador en cero: es el arranque de la
        # conversación, no una vuelta más sin entender.
        "vueltas_sin_definir": 0,
    }
