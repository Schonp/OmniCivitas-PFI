"""Lectura del día y la hora que pide el ciudadano para un turno."""

from datetime import datetime

import pytest

from app.agents.fechas import fecha_hora_dicha
from app.db.crud.turnos import ZONA_HORARIA

# Un miércoles a las 15.
AHORA = datetime(2026, 10, 28, 15, 0, tzinfo=ZONA_HORARIA)


@pytest.mark.parametrize(
    ("mensaje", "esperado"),
    [
        ("El jueves 29 de octubre a las 9", "2026-10-29 09:00"),
        ("entonces el jueves a las 9:30", "2026-10-29 09:30"),
        ("el viernes a las 10", "2026-10-30 10:00"),
        ("mañana a las 10 y media", "2026-10-29 10:30"),
        ("el 5/11 a las 11", "2026-11-05 11:00"),
        ("pasado mañana 9.30", "2026-10-30 09:30"),
        ("el lunes 10 hs", "2026-11-02 10:00"),
        # Un miércoles dicho un miércoles: hoy si la hora no pasó, si no el próximo.
        ("el miércoles a las 16:00", "2026-10-28 16:00"),
        ("el miércoles a las 9", "2026-11-04 09:00"),
        # "a las 2" en un turno de atención es de tarde.
        ("a las 2 del 3 de noviembre", "2026-11-03 14:00"),
        # Una fecha que ya pasó este año es del año que viene.
        ("el 2/3 a las 10", "2027-03-02 10:00"),
        # Por voz, la hora llega en palabras.
        ("el jueves a las diez.", "2026-10-29 10:00"),
        ("el viernes a la una y media", "2026-10-30 13:30"),
        ("mañana a las once y cuarto", "2026-10-29 11:15"),
    ],
)
def test_lee_dia_y_hora(mensaje, esperado):
    assert fecha_hora_dicha(mensaje, AHORA).strftime("%Y-%m-%d %H:%M") == esperado


@pytest.mark.parametrize(
    "mensaje",
    ["Laura Prueba, 30.111.298", "por la mañana a las 9", "el jueves", "a las 10", "quiero un turno"],
)
def test_sin_dia_o_sin_hora_no_inventa(mensaje):
    assert fecha_hora_dicha(mensaje, AHORA) is None
