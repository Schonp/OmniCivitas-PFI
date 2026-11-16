"""Tildes en lo que el organismo le escribe al ciudadano.

La descripción de un reclamo sale de las palabras del vecino
(`descripcion_del_ciudadano`), para que el modelo no le agregue datos que nadie
dio. El costo es que también hereda cómo las escribió: en una demo, "Hay un
arbol caido en la calle lima 717" volvió en la confirmación como "su reclamo
por arbol caido". Que el organismo escriba con faltas le resta seriedad a la
respuesta, aunque el error venga del vecino.

La corrección es a propósito acotada y predecible, no un corrector
ortográfico general:

- Una lista de palabras frecuentes en la atención municipal cuya forma sin
  tilde no existe en castellano. Las que sí existen con otro sentido quedan
  afuera, aunque sean comunes: "publico" (publicó), "transito" (transitó),
  "esta" (está), "mas" (más), "numero" (número).
- Las terminaciones "-cion" y "-sion", que en castellano siempre llevan tilde
  en singular ("direccion", "inspeccion", "pension").

No toca nombres propios ni calles, que no están en la lista, y no cambia lo que
ya viene bien escrito. El mensaje del ciudadano se guarda tal como lo mandó: se
corrige solo lo que sale del organismo.
"""

import re

_PALABRAS = {
    "arbol": "árbol",
    "arboles": "árboles",
    "caido": "caído",
    "caida": "caída",
    "caidos": "caídos",
    "caidas": "caídas",
    "semaforo": "semáforo",
    "semaforos": "semáforos",
    "vehiculo": "vehículo",
    "vehiculos": "vehículos",
    "camion": "camión",
    "electrico": "eléctrico",
    "electrica": "eléctrica",
    "electricos": "eléctricos",
    "electricas": "eléctricas",
    "energia": "energía",
    "linea": "línea",
    "lineas": "líneas",
    "desague": "desagüe",
    "desagues": "desagües",
    "baldio": "baldío",
    "baldios": "baldíos",
    "plastico": "plástico",
    "plasticos": "plásticos",
    "jardin": "jardín",
    "telefono": "teléfono",
    "telefonos": "teléfonos",
    "policia": "policía",
    "compañia": "compañía",
    "dia": "día",
    "dias": "días",
    "tambien": "también",
    "despues": "después",
    "todavia": "todavía",
    "ningun": "ningún",
    "algun": "algún",
    "aca": "acá",
    "ahi": "ahí",
    "aqui": "aquí",
    "alli": "allí",
    "rapido": "rápido",
    "rapida": "rápida",
    "facil": "fácil",
    "dificil": "difícil",
}

_PALABRA = re.compile(r"\b(" + "|".join(sorted(_PALABRAS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
# "direccion" -> "dirección". Solo en singular: el plural ("direcciones") no lleva tilde.
_TERMINACION = re.compile(r"\b(\w+?)([cs])ion\b", re.IGNORECASE)


def _como_el_original(original: str, corregida: str) -> str:
    """Respeta las mayúsculas del original: "Arbol" da "Árbol", "ARBOL" da "ÁRBOL"."""
    if original.isupper() and len(original) > 1:
        return corregida.upper()
    if original[0].isupper():
        return corregida[0].upper() + corregida[1:]
    return corregida


def _reemplazar_palabra(m: re.Match) -> str:
    original = m.group(0)
    return _como_el_original(original, _PALABRAS[original.lower()])


def _reemplazar_terminacion(m: re.Match) -> str:
    raiz, consonante = m.group(1), m.group(2)
    o = "Ó" if m.group(0).isupper() else "ó"
    n = "N" if m.group(0).isupper() else "n"
    i = "I" if m.group(0).isupper() else "i"
    return f"{raiz}{consonante}{i}{o}{n}"


_TOKEN = re.compile(r"\S+")


def _corregir_token(m: re.Match) -> str:
    token = m.group(0)
    # Un correo o un enlace se copian tal cual: "atencion@municipio.gob.ar"
    # con tilde deja de ser una dirección válida.
    if "@" in token or "/" in token or token.lower().startswith("www."):
        return token
    token = _PALABRA.sub(_reemplazar_palabra, token)
    return _TERMINACION.sub(_reemplazar_terminacion, token)


def con_tildes(texto: str | None) -> str | None:
    """El texto con las tildes que faltan en las palabras conocidas."""
    if not texto:
        return texto
    return _TOKEN.sub(_corregir_token, texto)
