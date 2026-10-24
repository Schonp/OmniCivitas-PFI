import pytest

from app.agents.identidad import extraer_identidad, responde_con_su_identidad


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Laura Prueba, 30.111.292", ("Laura Prueba", "30111292")),
        ("Soy Laura Prueba, DNI 30111292", ("Laura Prueba", "30111292")),
        ("Mi nombre es Marta Ruiz y mi DNI es 28.456.789", ("Marta Ruiz", "28456789")),
        ("soy laura prueba dni 30111292", ("Laura Prueba", "30111292")),
        ("Hay un pozo en Rivadavia 3200, soy Juan Pérez DNI 30111222", ("Juan Pérez", "30111222")),
        # Solo el número: no hay nombre que leer.
        ("30111292", (None, "30111292")),
        # Cuenta otra cosa además: no se adivina qué parte es el nombre.
        ("Hay un pozo enorme en Av Rivadavia 3200 frente al banco y mi dni es 30111222", (None, "30111222")),
    ],
)
def test_extrae_nombre_y_documento(texto, esperado):
    assert extraer_identidad(texto) == esperado


@pytest.mark.parametrize("texto", ["Hola, quiero un turno para el 12/11 a las 10", "Rivadavia 3200", "Mi teléfono es 1133334444"])
def test_sin_dni_no_hay_identidad(texto):
    assert extraer_identidad(texto) is None


def test_solo_cuenta_para_quien_no_esta_identificado():
    assert responde_con_su_identidad(False, "Laura, 30.111.292") is True
    assert responde_con_su_identidad(True, "Laura, 30.111.292") is False
    assert responde_con_su_identidad(False, "Hay un pozo en Rivadavia 3200") is False
