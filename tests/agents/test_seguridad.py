import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import decidir_ruta, procesar_mensaje
from app.agents.seguridad import (
    aviso_de_seguridad,
    con_aviso_de_seguridad,
    ofrece_dato_sensible,
    respuesta_dato_sensible,
)
from app.db.models import Canal


@pytest.mark.parametrize(
    "mensaje,numero",
    [
        ("Mi pareja me está amenazando y tengo miedo", "144"),
        ("Mi vecina sufre violencia de su marido", "144"),
        ("Me pegaron en mi casa", "144"),
        ("Se cayó una persona en un pozo y está lastimada", "107"),
        ("Se está prendiendo fuego un contenedor", "100"),
        ("Hay mucho olor a gas en la esquina de Medrano y Córdoba", "911"),
        ("Hay un cable de luz caído en la vereda y saltan chispas", "911"),
        ("Se inundó la esquina y hay gente atrapada en un auto", "911"),
    ],
)
def test_detecta_emergencias(mensaje, numero):
    aviso, _ = aviso_de_seguridad(mensaje)
    assert numero in aviso


@pytest.mark.parametrize(
    "mensaje",
    [
        "Hay un pozo enorme en Av. Rivadavia 3200",
        "Es un abuso lo que me cobraron de ABL",
        "No pasa el camión de la basura hace 8 días",
        "Me golpeé con un poste mal puesto, ¿dónde reclamo?",
        "Quiero sacar un turno para la licencia",
    ],
)
def test_no_avisa_en_mensajes_comunes(mensaje):
    """Un aviso de emergencia en cada reclamo se vuelve ruido que nadie lee."""
    assert aviso_de_seguridad(mensaje) is None


def test_el_aviso_va_adelante_de_la_respuesta():
    respuesta = con_aviso_de_seguridad(
        "Hay mucho olor a gas en la esquina", "Para registrar el reclamo necesito su DNI."
    )
    assert respuesta.startswith("Si hay olor a gas")
    assert respuesta.endswith("Para registrar el reclamo necesito su DNI.")


def test_no_repite_el_aviso_si_el_modelo_ya_lo_dio():
    del_modelo = "Que nadie se acerque al cable. Si hay riesgo, llame al 911. ¿Me da su DNI?"
    assert con_aviso_de_seguridad("Hay un cable caído", del_modelo) == del_modelo


def test_ante_violencia_el_911_solo_no_alcanza():
    """El 144 es el dato que el modelo omitía: si falta, el aviso va igual."""
    respuesta = con_aviso_de_seguridad("Me está amenazando mi pareja", "Llame al 911.")
    assert "144" in respuesta


@pytest.mark.parametrize(
    "mensaje",
    [
        "¿Te paso la clave de Mi Argentina así me sacás el turno?",
        "Te paso el número de mi tarjeta para pagar la multa",
        "Mi clave de home banking es 1234",
        "¿Necesitás mi contraseña?",
    ],
)
def test_detecta_claves_y_tarjetas(mensaje):
    assert ofrece_dato_sensible(mensaje)


@pytest.mark.parametrize(
    "mensaje",
    [
        "¿Necesito clave fiscal para habilitar el local?",
        "¿Dónde saco la tarjeta de estacionamiento?",
        "Quiero reclamar por un cobro en la tarjeta",
    ],
)
def test_una_consulta_de_requisitos_no_es_un_dato_sensible(mensaje):
    assert not ofrece_dato_sensible(mensaje)


def test_una_clave_va_al_ejecutor_aunque_el_intake_diga_tramite():
    """Pasó con el modelo real: "¿te paso la clave?" salió trámite y se derivó a
    una persona, que habría recibido la clave."""
    estado = {
        "mensaje": "¿Te paso la clave de Mi Argentina?",
        "ciudadano_id": "algun-uuid",
        "intencion": "tramite",
        "confianza": 0.9,
        "en_manos_humanas": True,
        "requiere_escalado": True,
    }
    assert decidir_ruta(estado) == "ejecutor"


async def test_el_ejecutor_contesta_la_clave_sin_el_modelo(db_session, mocker):
    from app.agents import ejecutor as mod

    modelo = MagicMock()
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    estado = {
        "mensaje": "¿Te paso la clave de Mi Argentina así me sacás el turno?",
        "canal": "whatsapp",
        "identificador": "+5491100000000",
        "ciudadano_id": str(uuid.uuid4()),
        "identificado": False,
        "caso_id": None,
        "historial": [],
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["respuesta"] == respuesta_dato_sensible(False)
    modelo.bind_tools.assert_not_called()


async def test_el_aviso_llega_aunque_el_modelo_este_caido(db_session, ciudadano, mocker):
    """El aviso no depende del modelo: con el servidor caído el caso se deriva
    y la respuesta igual empieza por el número de emergencias."""
    caido = MagicMock()
    caido.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=RuntimeError("caído"))
    caido.ainvoke = AsyncMock(side_effect=RuntimeError("caído"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=caido)
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=caido)

    final = await procesar_mensaje(
        db_session,
        mensaje="Mi pareja me está amenazando y tengo miedo",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=InMemorySaver(),
    )

    # Primero el aviso, aun antes del aviso de IA del primer contacto.
    assert final["respuesta"].startswith("Si está en peligro ahora, llame al 911")
    assert final["requiere_escalado"] is True
