"""Tildes en lo que el organismo le escribe al ciudadano (`app/core/ortografia.py`)."""

import pytest

from app.core.ortografia import con_tildes


def test_el_caso_de_la_demo():
    assert (
        con_tildes("Registré su reclamo por arbol caido en la calzada en Lima 717.")
        == "Registré su reclamo por árbol caído en la calzada en Lima 717."
    )


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Arbol caido", "Árbol caído"),
        ("ARBOL CAIDO", "ÁRBOL CAÍDO"),
        ("el semaforo de la esquina", "el semáforo de la esquina"),
        ("un vehiculo abandonado hace dias", "un vehículo abandonado hace días"),
        ("cable electrico suelto", "cable eléctrico suelto"),
    ],
)
def test_palabras_de_la_lista(entrada, esperado):
    assert con_tildes(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("la direccion exacta", "la dirección exacta"),
        ("pido una inspeccion", "pido una inspección"),
        ("la pension", "la pensión"),
        ("Direccion de Transito", "Dirección de Transito"),
    ],
)
def test_terminaciones_cion_y_sion(entrada, esperado):
    assert con_tildes(entrada) == esperado


def test_el_plural_no_lleva_tilde():
    assert con_tildes("las direcciones y las inspecciones") == "las direcciones y las inspecciones"


@pytest.mark.parametrize(
    "texto",
    [
        # Existen sin tilde con otro sentido: no se tocan.
        "esta calle se publico ayer",
        "mas tarde transito por la plaza",
        "anoto el numero",
        # Ya bien escrito.
        "árbol caído, dirección y teléfono",
        # Nombres y calles que no están en la lista.
        "Pedro Schon, Lima 717",
    ],
)
def test_no_toca_lo_que_no_conoce_o_ya_esta_bien(texto):
    assert con_tildes(texto) == texto


def test_no_rompe_correos_ni_enlaces():
    texto = "Escriba a atencion@municipio.gob.ar o entre a www.municipio.gob.ar/inspeccion"
    assert con_tildes(texto) == texto


def test_texto_vacio():
    assert con_tildes(None) is None
    assert con_tildes("") == ""
