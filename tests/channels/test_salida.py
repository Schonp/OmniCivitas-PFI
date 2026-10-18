import pytest

from app.channels import salida
from app.db.models import Canal, Ciudadano

CIUDADANO = Ciudadano(
    documento="28456789",
    nombre="Marta Ruiz",
    email="marta@correo.test",
    telefono="+5491133334444",
)


async def test_envia_por_email_al_contacto_del_ciudadano(mocker):
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(Canal.email, CIUDADANO, "Ya lo derivamos.")

    assert resultado.transmitido is True
    enviar.assert_awaited_once_with(
        "marta@correo.test", "Ya lo derivamos.", "Re: su consulta al organismo"
    )


async def test_envia_por_whatsapp_al_telefono(mocker):
    from datetime import datetime, timedelta, timezone

    enviar = mocker.patch.object(salida.whatsapp, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.whatsapp,
        CIUDADANO,
        "Ya lo derivamos.",
        ultimo_entrante=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    assert resultado.transmitido is True
    enviar.assert_awaited_once_with("+5491133334444", "Ya lo derivamos.")


async def test_el_canal_web_no_transmite_y_no_es_error(mocker):
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(Canal.web, CIUDADANO, "Ya lo derivamos.")

    assert resultado.transmitido is False
    assert resultado.motivo == "canal_sin_envio"
    enviar.assert_not_called()


async def test_sin_contacto_no_intenta_enviar(mocker):
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")
    sin_email = Ciudadano(documento="1", nombre="Sin Email", telefono="+5491100000000")

    resultado = await salida.enviar_al_ciudadano(Canal.email, sin_email, "Hola")

    assert resultado.transmitido is False
    assert resultado.motivo == "sin_contacto"
    enviar.assert_not_called()


async def test_una_falla_de_smtp_no_propaga_la_excepcion(mocker):
    """La interacción ya quedó guardada: perder la respuesta del operador por
    una caída de SMTP sería peor que registrarla y avisar."""
    mocker.patch.object(
        salida.canal_email, "enviar_mensaje", side_effect=TimeoutError("smtp caido")
    )

    resultado = await salida.enviar_al_ciudadano(Canal.email, CIUDADANO, "Ya lo derivamos.")

    assert resultado.transmitido is False
    assert resultado.motivo == "TimeoutError"


@pytest.mark.parametrize("texto", ["", "   ", "\n"])
async def test_ignora_texto_vacio(texto, mocker):
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(Canal.email, CIUDADANO, texto)

    assert resultado.transmitido is False
    assert resultado.motivo == "texto_vacio"
    enviar.assert_not_called()


def test_la_metadata_omite_el_motivo_cuando_hubo_exito():
    assert salida.ResultadoEnvio(True).como_metadata() == {"transmitido": True}
    assert salida.ResultadoEnvio(False, "sin_contacto").como_metadata() == {
        "transmitido": False,
        "motivo": "sin_contacto",
    }


# --- El operador responde sobre el hilo original ----------------------------


@pytest.mark.parametrize(
    "asunto,esperado",
    [
        ("Pileta", "Re: Pileta"),
        ("Re: Pileta", "Re: Pileta"),
        ("  Turno licencia  ", "Re: Turno licencia"),
        (None, "Re: su consulta al organismo"),
        ("", "Re: su consulta al organismo"),
    ],
)
def test_el_asunto_continua_el_hilo_sin_duplicar_el_re(asunto, esperado):
    assert salida._asunto_respuesta(asunto) == esperado


async def test_la_respuesta_del_operador_sale_con_el_asunto_del_caso(mocker):
    """Con el asunto genérico, al ciudadano le llegaba un correo suelto en vez de
    la continuación de su consulta."""
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")

    await salida.enviar_al_ciudadano(
        Canal.email, CIUDADANO, "La pileta es de uso libre.", asunto="Pileta"
    )

    enviar.assert_awaited_once_with(
        "marta@correo.test", "La pileta es de uso libre.", "Re: Pileta"
    )


# --- Ventana de 24 horas de WhatsApp ---------------------------------------


def test_la_ventana_se_mide_desde_el_ultimo_mensaje_del_ciudadano():
    from datetime import datetime, timedelta, timezone

    ahora = datetime.now(timezone.utc)

    assert salida.dentro_de_ventana(ahora - timedelta(hours=2)) is True
    assert salida.dentro_de_ventana(ahora - timedelta(hours=23, minutes=59)) is True
    assert salida.dentro_de_ventana(ahora - timedelta(hours=25)) is False
    # Sin ningún mensaje del ciudadano no hay ventana abierta.
    assert salida.dentro_de_ventana(None) is False


def test_la_ventana_tolera_un_timestamp_sin_zona():
    from datetime import datetime, timedelta, timezone

    ingenuo = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)

    assert salida.dentro_de_ventana(ingenuo) is True


async def test_fuera_de_ventana_no_se_intenta_el_envio_por_whatsapp(mocker):
    """Meta rechazaría el mensaje libre. Cortar antes deja el motivo en la
    auditoría, en vez de que el vecino nunca reciba nada y nadie se entere."""
    from datetime import datetime, timedelta, timezone

    enviar = mocker.patch.object(salida.whatsapp, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.whatsapp,
        CIUDADANO,
        "Ya derivamos su reclamo.",
        ultimo_entrante=datetime.now(timezone.utc) - timedelta(hours=30),
    )

    assert resultado.transmitido is False
    assert resultado.motivo == "fuera_de_ventana"
    enviar.assert_not_called()


async def test_dentro_de_ventana_el_envio_por_whatsapp_sale(mocker):
    from datetime import datetime, timedelta, timezone

    enviar = mocker.patch.object(salida.whatsapp, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.whatsapp,
        CIUDADANO,
        "Ya derivamos su reclamo.",
        ultimo_entrante=datetime.now(timezone.utc) - timedelta(hours=3),
    )

    assert resultado.transmitido is True
    enviar.assert_awaited_once_with("+5491133334444", "Ya derivamos su reclamo.")


async def test_el_correo_no_tiene_ventana(mocker):
    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.email, CIUDADANO, "Ya derivamos su reclamo.", ultimo_entrante=None
    )

    assert resultado.transmitido is True
    enviar.assert_awaited_once()
