"""Horarios de turno válidos para los tests, calculados desde hoy.

Las reservas ya no aceptan cualquier fecha: tiene que ser un día hábil de la
agenda, a futuro y dentro de la anticipación máxima. Una fecha fija en un test
se vuelve pasado con el tiempo y el test empieza a fallar sin que cambie nada.
"""

from datetime import date, datetime, timedelta

from app.db.crud.turnos import ZONA_HORARIA


def dia_habil(desde_hoy: int = 2) -> date:
    """El primer día de lunes a viernes a partir de `desde_hoy` días."""
    dia = datetime.now(ZONA_HORARIA).date() + timedelta(days=desde_hoy)
    while dia.weekday() >= 5:
        dia += timedelta(days=1)
    return dia


def horario(desde_hoy: int = 2, hora: str = "10:00") -> str:
    """"AAAA-MM-DD HH:MM", el formato con el que el agente pide un turno."""
    return f"{dia_habil(desde_hoy).isoformat()} {hora}"


def momento(desde_hoy: int = 2, hora: str = "10:00") -> datetime:
    horas, minutos = (int(parte) for parte in hora.split(":"))
    return datetime.combine(
        dia_habil(desde_hoy), datetime.min.time().replace(hour=horas, minute=minutos), tzinfo=ZONA_HORARIA
    )
