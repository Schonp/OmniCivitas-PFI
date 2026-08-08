import uuid

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.channels import web
from app.db.models import ActorInteraccion, Canal, Caso, Ciudadano, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent
from app.schemas.chat import InicioSesionChat


async def test_identificar_ciudadano_da_de_alta_en_primer_contacto(db_session):
    datos = InicioSesionChat(
        documento="30111222",
        nombre="Ana Gómez",
        email="ana.gomez@test.com",
        telefono=None,
    )

    ciudadano = await web.identificar_ciudadano(db_session, datos)

    assert ciudadano.id is not None
    assert ciudadano.documento == "30111222"
    persistido = (
        (await db_session.execute(select(Ciudadano).where(Ciudadano.documento == "30111222")))
        .scalars()
        .first()
    )
    assert persistido is not None
    assert persistido.email == "ana.gomez@test.com"


async def test_identificar_ciudadano_reutiliza_documento_existente(db_session, ciudadano):
    datos = InicioSesionChat(
        documento=ciudadano.documento,
        nombre="Juan Pérez",
        email=ciudadano.email,
        telefono="+5491199887766",
    )

    identificado = await web.identificar_ciudadano(db_session, datos)

    assert identificado.id == ciudadano.id
    assert identificado.telefono == "+5491199887766"


async def test_identificador_de_prefiere_email(ciudadano):
    assert web.identificador_de(ciudadano) == ciudadano.email


async def test_identificador_de_usa_telefono_sin_email():
    sin_email = Ciudadano(documento="1", nombre="Sin Email", telefono="+5491100000000")
    assert web.identificador_de(sin_email) == "+5491100000000"


async def test_recibir_mensaje_crea_caso_y_persiste_interacciones(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms(
        ClasificacionIntent(
            intencion="reclamo", entidades={"categoria": "infraestructura"}, confianza=0.9
        ),
        respuestas_ejecutor=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reclamo",
                        "args": {
                            "descripcion": "No pasa el camión de basura",
                            "categoria": "servicio",
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Registré su reclamo. Le avisaremos por este medio."),
        ],
    )

    final = await web.recibir_mensaje(
        db_session, ciudadano=ciudadano, mensaje="Hace una semana que no pasa el camión"
    )

    assert final["respuesta"] == "Registré su reclamo. Le avisaremos por este medio."
    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo
    assert caso.canal_origen == Canal.web

    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.canal for i in interacciones} == {Canal.web}
    assert {i.actor for i in interacciones} == {
        ActorInteraccion.ciudadano,
        ActorInteraccion.agente_ia,
    }
