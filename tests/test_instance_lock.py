"""El candado que evita dos pollers sobre el mismo buzón.

Existe porque pasó: dos procesos de `revisar_correo` levantaron el mismo correo
antes de que ninguno lo marcara como leído, y el ciudadano recibió dos veces la
respuesta del agente.
"""

import pytest

from app.core.instance_lock import InstanciaEnUso, instancia_unica, ruta_de_candado

NOMBRE = "test-candado"


def test_el_segundo_no_puede_tomar_el_candado():
    with instancia_unica(NOMBRE):
        with pytest.raises(InstanciaEnUso):
            with instancia_unica(NOMBRE):
                pytest.fail("no debería haber entrado")


def test_al_salir_queda_libre_para_el_siguiente():
    """Un poller que se para tiene que dejar arrancar al que venga después."""
    with instancia_unica(NOMBRE):
        pass

    with instancia_unica(NOMBRE) as ruta:
        assert ruta == ruta_de_candado(NOMBRE)


def test_una_excepcion_adentro_igual_suelta_el_candado():
    with pytest.raises(ValueError):
        with instancia_unica(NOMBRE):
            raise ValueError("se cayó la pasada por el buzón")

    with instancia_unica(NOMBRE):
        pass


def test_candados_con_nombres_distintos_no_se_estorban():
    with instancia_unica(NOMBRE):
        with instancia_unica(f"{NOMBRE}-otro"):
            pass
