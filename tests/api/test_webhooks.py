"""El webhook de Meta es público: lo protege la firma del proveedor, no JWT."""

import json

from app.api import webhooks
from app.channels import whatsapp
from app.db.models import Ciudadano


class _FabricaDeSesion:
    """La respuesta sale en una tarea de fondo, cuando la sesión del request ya
    se cerró, así que el webhook abre la suya. Acá se le pasa la de prueba."""

    def __init__(self, sesion):
        self.sesion = sesion

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.sesion

    async def __aexit__(self, *_):
        return False

URL = "/api/webhooks/whatsapp"
WA_ID = "5491133334444"
TELEFONO = "+5491133334444"


def _payload(texto: str = "El poste no anda"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"wa_id": WA_ID, "profile": {"name": "Marta"}}],
                            "messages": [
                                {
                                    "from": WA_ID,
                                    "id": "wamid.ABC",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }


async def test_la_verificacion_devuelve_el_desafio(client, mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_verify_token", "secreto")

    respuesta = await client.get(
        URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "secreto",
            "hub.challenge": "98765",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.text == "98765"


async def test_la_verificacion_rechaza_un_token_ajeno(client, mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_verify_token", "secreto")

    respuesta = await client.get(
        URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "intruso",
            "hub.challenge": "98765",
        },
    )

    assert respuesta.status_code == 403


async def test_rechaza_si_la_firma_no_valida(client, mocker):
    mocker.patch.object(whatsapp, "validar_firma", return_value=False)
    recibir = mocker.patch.object(whatsapp, "recibir_mensaje")

    respuesta = await client.post(URL, json=_payload())

    assert respuesta.status_code == 403
    recibir.assert_not_called()


async def test_procesa_el_mensaje_y_programa_la_respuesta(
    client, db_session, mocker
):
    db_session.add(
        Ciudadano(documento="55111222", nombre="Marta", telefono=TELEFONO)
    )
    await db_session.commit()

    mocker.patch.object(whatsapp, "validar_firma", return_value=True)
    recibir = mocker.patch.object(
        whatsapp, "recibir_mensaje", return_value={"respuesta": "Registré su reclamo."}
    )
    mocker.patch.object(webhooks, "async_session_factory", _FabricaDeSesion(db_session))
    enviar = mocker.patch.object(whatsapp, "enviar_mensaje")

    respuesta = await client.post(URL, json=_payload())

    assert respuesta.status_code == 204
    # El wa_id llega sin "+" y se normaliza a formato internacional.
    assert recibir.await_args.kwargs["telefono"] == TELEFONO
    assert recibir.await_args.kwargs["nombre"] == "Marta"
    # La respuesta sale en background: Meta corta si el webhook tarda.
    enviar.assert_awaited_once_with(TELEFONO, "Registré su reclamo.")


async def test_un_fallo_de_envio_no_revienta_el_webhook(client, db_session, mocker):
    """Con el token de Meta vencido, el envío terminaba en un traceback de ASGI.
    La interacción ya está guardada: perder la respuesta es malo, pero romper el
    webhook hace que Meta reintente el mismo mensaje una y otra vez."""
    db_session.add(
        Ciudadano(documento="55111333", nombre="Marta", telefono=TELEFONO)
    )
    await db_session.commit()

    mocker.patch.object(whatsapp, "validar_firma", return_value=True)
    mocker.patch.object(
        whatsapp, "recibir_mensaje", return_value={"respuesta": "Registré su reclamo."}
    )
    mocker.patch.object(webhooks, "async_session_factory", _FabricaDeSesion(db_session))
    mocker.patch.object(
        whatsapp, "enviar_mensaje", side_effect=RuntimeError("token vencido")
    )

    respuesta = await client.post(URL, json=_payload())

    assert respuesta.status_code == 204


async def test_los_acuses_de_entrega_no_entran_al_grafo(client, mocker):
    """Meta manda por el mismo webhook las confirmaciones de entrega y lectura."""
    mocker.patch.object(whatsapp, "validar_firma", return_value=True)
    recibir = mocker.patch.object(whatsapp, "recibir_mensaje")

    respuesta = await client.post(
        URL,
        json={
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {"statuses": [{"id": "wamid.X", "status": "read"}]},
                        }
                    ]
                }
            ],
        },
    )

    assert respuesta.status_code == 204
    recibir.assert_not_called()


async def test_un_cuerpo_que_no_es_json_no_rompe(client, mocker):
    mocker.patch.object(whatsapp, "validar_firma", return_value=True)

    respuesta = await client.post(URL, content=b"esto no es json")

    assert respuesta.status_code == 204


async def test_no_responde_si_el_grafo_no_produjo_texto(client, mocker):
    mocker.patch.object(whatsapp, "validar_firma", return_value=True)
    mocker.patch.object(whatsapp, "recibir_mensaje", return_value={"respuesta": None})
    enviar = mocker.patch.object(whatsapp, "enviar_mensaje")

    respuesta = await client.post(URL, json=_payload())

    assert respuesta.status_code == 204
    enviar.assert_not_called()


# --- Respuesta del operador: sale por el canal del caso ---------------------


async def _caso_por_email(client, auth_headers, ciudadano) -> str:
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "email"},
        headers=auth_headers,
    )
    return creado.json()["id"]


async def test_la_respuesta_del_operador_se_transmite_y_queda_auditada(
    client, auth_headers, ciudadano, mocker
):
    from app.channels import salida

    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")
    caso_id = await _caso_por_email(client, auth_headers, ciudadano)

    respuesta = await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Ya derivamos su reclamo a Higiene Urbana."},
        headers=auth_headers,
    )

    assert respuesta.status_code == 201
    # El caso se creó por API, sin asunto de correo: cae en el genérico.
    enviar.assert_awaited_once_with(
        ciudadano.email,
        "Ya derivamos su reclamo a Higiene Urbana.",
        "Re: su consulta al organismo",
    )

    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    envios = [a for a in auditoria.json() if a["accion"] == "envio_saliente"]
    assert len(envios) == 1
    assert envios[0]["metadata"] == {"transmitido": True, "canal": "email"}


async def test_la_nota_interna_no_sale_del_organismo(
    client, auth_headers, ciudadano, mocker
):
    from app.channels import salida

    enviar = mocker.patch.object(salida.canal_email, "enviar_mensaje")
    caso_id = await _caso_por_email(client, auth_headers, ciudadano)

    await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Ojo: ya reclamó tres veces.", "interna": True},
        headers=auth_headers,
    )

    enviar.assert_not_called()
    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    assert not [a for a in auditoria.json() if a["accion"] == "envio_saliente"]


async def test_si_el_envio_falla_la_respuesta_igual_queda_registrada(
    client, auth_headers, ciudadano, mocker
):
    from app.channels import salida

    mocker.patch.object(
        salida.canal_email, "enviar_mensaje", side_effect=TimeoutError("smtp caido")
    )
    caso_id = await _caso_por_email(client, auth_headers, ciudadano)

    respuesta = await client.post(
        f"/api/casos/{caso_id}/respuesta",
        json={"contenido": "Ya derivamos su reclamo."},
        headers=auth_headers,
    )

    assert respuesta.status_code == 201
    interacciones = await client.get(
        f"/api/casos/{caso_id}/interacciones", headers=auth_headers
    )
    assert interacciones.json()[0]["contenido"] == "Ya derivamos su reclamo."

    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    envio = [a for a in auditoria.json() if a["accion"] == "envio_saliente"][0]
    assert envio["metadata"]["transmitido"] is False
    assert envio["metadata"]["motivo"] == "TimeoutError"
