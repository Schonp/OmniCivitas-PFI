"""Lectura del día y la hora que el ciudadano pide para un turno.

Pasar "el jueves a las 9:30" a "2026-10-29 09:30" no se le deja solo al modelo.
En las pruebas con el modelo real, inventaba la fecha cuando el ciudadano
todavía no la había dicho, y confirmaba reservas que nunca hizo. Las formas de
decir un día y una hora son pocas y fijas: se leen con reglas, igual que el DNI
(ver `app/agents/identidad.py`), y lo que dijo el ciudadano manda sobre lo que
propone el modelo.
"""

import re
from datetime import date, datetime, time, timedelta

DIAS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_FECHA_NUMERICA = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b")
_FECHA_CON_MES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\b")
_DIA_SEMANA = re.compile(r"\b(" + "|".join(DIAS) + r")\b")
_PROXIMO = re.compile(r"\b(proximo|que viene)\b")
# "mañana" es el día siguiente, salvo en "a la mañana" o "por la mañana".
_MANANA = re.compile(r"(?<!la )\bmanana\b")

_HORAS = [
    # "a las 9", "a las 9:30", "a la 1"
    re.compile(r"\ba\s+las?\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*y\s+(media|cuarto))?\b"),
    # "9:30", "9.30 hs"
    re.compile(r"\b(\d{1,2})[:.](\d{2})\b(?!\s*/)"),
    # "10 hs", "10 horas"
    re.compile(r"\b(\d{1,2})\s*(?:h|hs|horas)\b()"),
]


def _normalizado(texto: str) -> str:
    return texto.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))


def _hora_dicha(texto: str) -> time | None:
    for patron in _HORAS:
        coincidencia = patron.search(texto)
        if coincidencia is None:
            continue
        horas = int(coincidencia.group(1))
        minutos = coincidencia.group(2)
        extra = coincidencia.group(3) if patron.groups >= 3 else None
        minutos = int(minutos) if minutos else {"media": 30, "cuarto": 15}.get(extra or "", 0)
        # Un turno de atención es de día: "a las 3" es a las 15.
        if 1 <= horas <= 7:
            horas += 12
        if horas <= 23 and minutos <= 59:
            return time(horas, minutos)
    return None


def _dia_dicho(texto: str, hoy: date) -> tuple[date | None, int | None]:
    """El día, o (None, día de la semana) si solo nombró el día de la semana:
    cuál de todos depende de la hora (ver `fecha_hora_dicha`)."""
    numerica = _FECHA_NUMERICA.search(texto)
    con_mes = _FECHA_CON_MES.search(texto)
    if numerica or con_mes:
        if numerica:
            dia, mes = int(numerica.group(1)), int(numerica.group(2))
            anio = numerica.group(3)
            anio = (2000 + int(anio) if len(anio) == 2 else int(anio)) if anio else None
        else:
            dia, mes, anio = int(con_mes.group(1)), MESES[con_mes.group(2)], None
        try:
            fecha = date(anio or hoy.year, mes, dia)
        except ValueError:
            return None, None
        if anio is None and fecha < hoy:
            fecha = date(hoy.year + 1, mes, dia)
        return fecha, None
    if re.search(r"\bpasado\s+manana\b", texto):
        return hoy + timedelta(days=2), None
    if _MANANA.search(texto):
        return hoy + timedelta(days=1), None
    if re.search(r"\bhoy\b", texto):
        return hoy, None
    semana = _DIA_SEMANA.search(texto)
    if semana:
        return None, DIAS[semana.group(1)]
    return None, None


def fecha_hora_dicha(mensaje: str, ahora: datetime) -> datetime | None:
    """El día y la hora que pide el mensaje, en la zona de `ahora`, o None si no
    trae las dos cosas."""
    texto = _normalizado(mensaje or "")
    hora = _hora_dicha(texto)
    if hora is None:
        return None
    hoy = ahora.date()
    dia, dia_semana = _dia_dicho(texto, hoy)
    if dia is None and dia_semana is None:
        return None
    if dia is None:
        adelanto = (dia_semana - hoy.weekday()) % 7
        dia = hoy + timedelta(days=adelanto)
        # "El jueves" dicho un jueves es hoy si todavía no pasó la hora; si no,
        # o si dijo "el próximo", es el de la semana que viene.
        if adelanto == 0 and (datetime.combine(dia, hora, tzinfo=ahora.tzinfo) <= ahora or _PROXIMO.search(texto)):
            dia += timedelta(days=7)
    return datetime.combine(dia, hora, tzinfo=ahora.tzinfo)


def hora_dicha(mensaje: str) -> time | None:
    """Solo la hora ("el de las 10:30"), para elegir entre horarios ofrecidos."""
    return _hora_dicha(_normalizado(mensaje or ""))
