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

    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "")
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


async def test_fuera_de_ventana_sale_la_plantilla_si_hay_una(mocker):
    from datetime import datetime, timedelta, timezone

    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "seguimiento_caso")
    libre = mocker.patch.object(salida.whatsapp, "enviar_mensaje")
    plantilla = mocker.patch.object(salida.whatsapp, "enviar_plantilla")

    resultado = await salida.enviar_al_ciudadano(
        Canal.whatsapp,
        CIUDADANO,
        "Ya derivamos su reclamo.",
        ultimo_entrante=datetime.now(timezone.utc) - timedelta(hours=30),
    )

    assert resultado.transmitido is True
    assert resultado.como_metadata() == {"transmitido": True, "plantilla": True}
    plantilla.assert_awaited_once_with("+5491133334444", "Ya derivamos su reclamo.")
    libre.assert_not_called()


async def test_un_texto_que_no_entra_en_la_plantilla_no_se_envia(mocker):
    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "seguimiento_caso")
    plantilla = mocker.patch.object(salida.whatsapp, "enviar_plantilla")
    largo = "a" * (salida.whatsapp.MAX_PARAMETRO_PLANTILLA + 1)

    resultado = await salida.enviar_al_ciudadano(Canal.whatsapp, CIUDADANO, largo)

    assert resultado.transmitido is False
    assert resultado.motivo == "texto_largo_para_plantilla"
    plantilla.assert_not_called()


# --- Casos que llegaron por voz ---------------------------------------------


def test_la_respuesta_escrita_de_un_caso_de_voz_sale_por_whatsapp():
    assert salida.canal_de_envio(Canal.voz) == Canal.whatsapp
    assert salida.canal_de_envio(Canal.whatsapp) == Canal.whatsapp
    assert salida.canal_de_envio(Canal.email) == Canal.email


async def test_caso_de_voz_dentro_de_ventana_sale_como_mensaje_libre(mocker):
    """No hay operadores por teléfono: la respuesta va por WhatsApp al número
    desde el que llamó el ciudadano."""
    from datetime import datetime, timedelta, timezone

    enviar = mocker.patch.object(salida.whatsapp, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.voz,
        CIUDADANO,
        "Ya derivamos su reclamo.",
        ultimo_entrante=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    assert resultado.transmitido is True
    enviar.assert_awaited_once_with("+5491133334444", "Ya derivamos su reclamo.")


async def test_caso_de_voz_de_quien_nunca_escribio_usa_la_plantilla(mocker):
    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "seguimiento_caso")
    plantilla = mocker.patch.object(salida.whatsapp, "enviar_plantilla")

    resultado = await salida.enviar_al_ciudadano(
        Canal.voz, CIUDADANO, "Ya derivamos su reclamo.", ultimo_entrante=None
    )

    assert resultado.transmitido is True
    assert resultado.via_plantilla is True
    plantilla.assert_awaited_once_with("+5491133334444", "Ya derivamos su reclamo.")


async def test_caso_de_voz_sin_plantilla_queda_fuera_de_ventana(mocker):
    mocker.patch.object(salida.settings, "whatsapp_plantilla_seguimiento", "")
    enviar = mocker.patch.object(salida.whatsapp, "enviar_mensaje")

    resultado = await salida.enviar_al_ciudadano(
        Canal.voz, CIUDADANO, "Ya derivamos su reclamo.", ultimo_entrante=None
    )

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


async def test_si_la_respuesta_no_se_puede_enviar_el_caso_pasa_a_una_persona(db_session, ciudadano, mocker):
    """RNF-03: si Meta o el servidor de correo rechazan la respuesta, el
    ciudadano no la recibe y tiene que retomarlo un operador."""
    from app.db.models import Auditoria, Caso, EstadoCaso, TipoCaso
    from sqlalchemy import select

    caso = Caso(ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo, canal_origen=Canal.email, canal_actual=Canal.email)
    db_session.add(caso)
    await db_session.commit()
    mocker.patch.object(salida.canal_email, "enviar_mensaje", side_effect=TimeoutError("smtp caido"))

    resultado = await salida.responder_al_ciudadano(
        db_session, canal=Canal.email, ciudadano=ciudadano, texto="Registré su reclamo.", caso_id=caso.id
    )

    assert resultado.transmitido is False
    estado = (await db_session.execute(
        select(Caso.estado).where(Caso.id == caso.id).execution_options(populate_existing=True)
    )).scalar_one()
    assert estado in (EstadoCaso.escalado, EstadoCaso.en_progreso)
    motivos = (await db_session.execute(
        select(Auditoria.metadata_).where(Auditoria.caso_id == caso.id, Auditoria.accion == "escalado")
    )).scalars().all()
    assert motivos == [{"motivo": "falla_envio"}]
