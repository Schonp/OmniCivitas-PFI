"""Avisos de emergencia y pedidos de datos sensibles, resueltos en el código.

La v3 del modelo aprendió las pautas de emergencia del organismo, pero no
siempre las aplica: en una prueba con el modelo real, un "olor a gas en la
esquina" se contestó pidiendo el DNI, sin ningún aviso, y un "mi pareja me está
amenazando" se derivó a una persona sin nombrar el 911 ni el 144. Igual que con
el aviso de IA (`aviso_ia.py`), lo que no puede faltar no se deja librado a que
el modelo se acuerde: se detecta por palabras y se antepone un texto fijo.

Las reglas son a propósito acotadas. Un aviso de más ante "me golpeé con un
pozo" es tolerable; uno que salte en cada reclamo de tasas ("es un abuso lo que
cobran") se vuelve ruido, y por eso esas palabras no están.
"""

import re

_EMERGENCIAS = ("911", "100", "107")

# (patrón, aviso, números que ya alcanzan si la respuesta los nombra). El orden
# es la prioridad: si un mensaje cae en dos, va el primero.
_AVISOS: list[tuple[re.Pattern, str, tuple[str, ...]]] = [
    (
        re.compile(
            r"\b(?:me|nos|la|lo|le|les)\s+(?:est[aá]n?\s+)?"
            r"(?:amenaz\w*|peg(?:a|an|ó|o|aron|ando)|golpe(?:a|an|ó|aron|ando))\b"
            r"|\bviolencia\b",
            re.IGNORECASE,
        ),
        "Si está en peligro ahora, llame al 911. Para orientación y ayuda en situaciones de "
        "violencia de género puede llamar al 144, las 24 horas y en forma gratuita.",
        ("144",),
    ),
    (
        re.compile(
            r"\b(?:herid[oa]s?|lastimad[oa]s?|sangr(?:a|ando)|desmay\w*|inconsciente|no respira)\b",
            re.IGNORECASE,
        ),
        "Si hay una persona lastimada, llame primero a emergencias médicas al 107.",
        _EMERGENCIAS,
    ),
    (
        re.compile(r"\b(?:fuego|incendi\w*|se\s+(?:est[aá]\s+)?quemando)\b", re.IGNORECASE),
        "Si hay fuego, aléjese del lugar y llame ya a los bomberos al 100.",
        _EMERGENCIAS,
    ),
    (
        re.compile(r"\b(?:olor|huele|p[eé]rdida|escape|fuga)\s+(?:a|de)\s+gas\b", re.IGNORECASE),
        "Si hay olor a gas, no encienda luces ni fuego y aléjese. Si el olor es fuerte, "
        "llame al 911 desde un lugar seguro.",
        _EMERGENCIAS,
    ),
    (
        re.compile(
            r"\bcables?\s+(?:de\s+luz\s+)?(?:ca[ií]d|suelt|cortad|pelad)\w*"
            r"|\bchispas?\b|\belectrocut\w*",
            re.IGNORECASE,
        ),
        "Por favor, que nadie se acerque al cable. Si hay riesgo inmediato, llame al 911.",
        _EMERGENCIAS,
    ),
    (
        re.compile(r"\batrapad[oa]s?\b", re.IGNORECASE),
        "Si hay personas en peligro, llame ya al 911.",
        _EMERGENCIAS,
    ),
]


def aviso_de_seguridad(mensaje: str | None) -> tuple[str, tuple[str, ...]] | None:
    """(aviso, números que lo cubren) si el mensaje cuenta una emergencia."""
    for patron, aviso, numeros in _AVISOS:
        if patron.search(mensaje or ""):
            return aviso, numeros
    return None


def con_aviso_de_seguridad(mensaje: str | None, respuesta: str | None) -> str | None:
    """La respuesta con el aviso adelante, salvo que ya nombre el número."""
    encontrado = aviso_de_seguridad(mensaje)
    if not respuesta or encontrado is None:
        return respuesta
    aviso, numeros = encontrado
    if any(re.search(rf"\b{numero}\b", respuesta) for numero in numeros):
        return respuesta
    return f"{aviso}\n\n{respuesta}"


# Ofrecer una clave o la tarjeta, o preguntar si hace falta. "¿Necesito la clave
# fiscal?" es una consulta de requisitos y no entra: pide "mi clave" a otro.
_DATO_SENSIBLE = re.compile(
    r"\b(?:te|le|les)\s+(?:paso|doy|mando|env[ií]o|dejo|digo)\s+(?:mi|la|el|los|mis)?\s*"
    r"(?:clave|contraseña|password|pin|token|cvv|tarjeta|n[uú]mero de (?:mi )?tarjeta|datos de (?:mi )?tarjeta)"
    r"|\bmi\s+(?:clave|contraseña|password|pin)(?:\s+\w+){0,3}\s+es\b"
    r"|\bnecesit\w*s\s+mi\s+(?:clave|contraseña|password|pin|tarjeta)",
    re.IGNORECASE,
)


def ofrece_dato_sensible(mensaje: str | None) -> bool:
    return bool(_DATO_SENSIBLE.search(mensaje or ""))


def respuesta_dato_sensible(identificado: bool) -> str:
    datos = (
        "Sus datos ya los tengo."
        if identificado
        else "Para un reclamo, un turno o una consulta me alcanza con su nombre completo y su DNI."
    )
    return (
        "Por favor, no me pase claves, contraseñas ni datos de tarjetas: nunca se los voy a "
        f"pedir por este medio. {datos} ¿En qué lo puedo ayudar?"
    )
