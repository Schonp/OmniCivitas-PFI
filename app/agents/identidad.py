"""Reconocimiento de la respuesta del ciudadano al pedido de nombre y DNI.

Registrar la identidad no se le deja al modelo. En las pruebas sobre el sistema
completo, el modelo a veces volvía a pedir los datos que el ciudadano acababa
de dar, y el intake llegaba a clasificar "Laura Pérez, 30.111.291" como un
trámite, que se deriva directo a una persona. Un DNI tiene una forma fija y el
nombre viene al lado: se puede leer con reglas, sin depender de una inferencia.
"""

import re

# Un DNI argentino: 7 u 8 dígitos, juntos o separados en grupos ("30.111.291",
# "30111291"). Por voz, el reconocimiento lo transcribe también con guiones o
# espacios ("30-885-211"): pasó en la primera llamada de prueba, y sin esto el
# DNI dictado no se registraba y el agente lo volvía a pedir.
DNI = re.compile(r"\b\d{1,2}[.\- ]?\d{3}[.\- ]?\d{3}\b")

# La presentación no distingue mayúsculas; el nombre sí: arranca con mayúscula,
# lo que evita llevarse la palabra siguiente ("soy Juan Pérez, DNI ...").
_PRESENTACION = re.compile(
    r"(?i:soy|me llamo|mi nombre es)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3})"
)
_RELLENO = {
    "soy", "me", "llamo", "mi", "nombre", "es", "y", "el", "la", "de", "dni",
    "documento", "número", "numero", "nro", "hola", "buenas", "buen", "día", "dia",
    "tardes", "noches", "mis", "datos", "son", "con",
}
_MAX_PALABRAS_DE_NOMBRE = 5


def extraer_identidad(texto: str) -> tuple[str | None, str] | None:
    """(nombre, documento) si el texto trae un DNI; None si no lo trae.

    El nombre sale de una presentación explícita ("soy Laura Pérez") o, si el
    mensaje es solo el dato pedido ("Laura Pérez, 30.111.291"), de las palabras
    que acompañan al número. Si el mensaje cuenta además otra cosa, no se
    adivina qué parte es el nombre: se devuelve None en su lugar.
    """
    coincidencia = DNI.search(texto or "")
    if coincidencia is None:
        return None
    documento = re.sub(r"\D", "", coincidencia.group(0))

    presentacion = _PRESENTACION.search(texto)
    if presentacion:
        palabras = [p for p in presentacion.group(1).split() if p.lower() not in _RELLENO]
        if palabras:
            return _formatear(" ".join(palabras)), documento

    resto = (texto[: coincidencia.start()] + " " + texto[coincidencia.end():])
    palabras = [p for p in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]+", resto) if p.lower() not in _RELLENO]
    if 0 < len(palabras) <= _MAX_PALABRAS_DE_NOMBRE:
        return _formatear(" ".join(palabras)), documento
    return None, documento


def _formatear(nombre: str) -> str:
    return " ".join(p[:1].upper() + p[1:].lower() for p in nombre.split())


def responde_con_su_identidad(identificado: bool, mensaje: str | None) -> bool:
    """Quien todavía no informó su DNI y manda uno está contestando el pedido de
    datos del agente: el mensaje continúa el caso y lo resuelve el ejecutor."""
    return not identificado and bool(DNI.search(mensaje or ""))


# Un saludo o un agradecimiento con nombre: "Hola, Juan Pérez." / "Gracias Laura,".
_SALUDO_CON_NOMBRE = re.compile(
    r"\b((?i:hola|buen(?:os)?\s+d[ií]as?|buenas(?:\s+tardes|\s+noches)?|gracias|estimad[oa]))"
    r"\s*,?\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3})"
)


def sin_nombre_inventado(texto: str, conocido: str) -> str:
    """Saca del saludo un nombre que no aparece en lo que el modelo vio.

    Pasó en una prueba: ante un olor a gas, el modelo intentó registrar a un
    "Juan Pérez" con un DNI inventado. El control de `dni_dicho` frenó el
    registro, pero la respuesta final saludaba igual a "Juan Pérez". El modelo
    solo puede saber el nombre por la conversación, así que todo nombre que no
    esté en ella es inventado.
    """
    palabras_conocidas = set(re.findall(r"\w+", conocido.lower()))

    def reemplazo(coincidencia: re.Match) -> str:
        nombre = coincidencia.group(2).split()
        if all(palabra.lower() in palabras_conocidas for palabra in nombre):
            return coincidencia.group(0)
        return coincidencia.group(1)

    return _SALUDO_CON_NOMBRE.sub(reemplazo, texto)
