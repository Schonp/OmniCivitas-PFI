"""Título automático para los casos que ninguna tool nombra.

El reclamo y el turno se titulan al registrarse ("Reclamo por pozo en...",
"Turno de ..."). Una consulta o un caso derivado a una persona no pasan por
ninguna tool, y sin título el saludo de la llamada los nombraba con las
primeras palabras del vecino cortadas a la mitad ("Quiero reservar un turno
para renovar la licencia de"). Se arma uno corto con lo que pidió, sin el
saludo ni los signos de pregunta. El supervisor lo puede corregir desde el
panel, y ninguna tool pisa un título que ya existe.
"""

import re

from app.db.models import TipoCaso

TITULO_MAX = 70
# Más corto que esto no dice de qué se trata (un "3" elegido del menú, un "sí").
MIN_CARACTERES = 6

_SALUDO_INICIAL = re.compile(
    r"^(?:(?:hola|buenas(?: tardes| noches)?|buen d[ií]a|buenos d[ií]as|qu[eé] tal)[\s,.!¡]*)+",
    re.IGNORECASE,
)
_SIGNOS = re.compile(r"[¿?¡!]")
_CONECTORES = {
    "a", "al", "con", "de", "del", "el", "en", "la", "las", "lo", "los", "o", "para",
    "por", "que", "se", "su", "sus", "un", "una", "y", "mi", "mis",
}


def titulo_automatico(tipo: TipoCaso, mensaje: str | None) -> str | None:
    """"Qué horario tiene el centro de salud". Sin el tipo adelante: el panel
    lo muestra en su propia etiqueta. None si el mensaje no alcanza para decir
    de qué se trata."""
    texto = _SIGNOS.sub("", " ".join((mensaje or "").split()))
    texto = _SALUDO_INICIAL.sub("", texto).strip(" ,.;:")
    if len(texto) < MIN_CARACTERES or texto.isdigit():
        return None
    titulo = texto[0].upper() + texto[1:]
    if len(titulo) > TITULO_MAX:
        palabras = titulo[:TITULO_MAX].rsplit(" ", 1)[0].split()
        # Cortado, que no termine en "por", "de la", "y": se lee como un error.
        while palabras and palabras[-1].lower().strip(",.;:") in _CONECTORES:
            palabras.pop()
        titulo = " ".join(palabras)
    return titulo.rstrip(" ,.;:")
