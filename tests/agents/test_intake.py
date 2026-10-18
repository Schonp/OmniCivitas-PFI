from unittest.mock import AsyncMock, MagicMock

from app.agents.intake import nodo_intake
from app.schemas.agente import ClasificacionIntent


def _mock_intake(mocker, clasificacion: ClasificacionIntent) -> None:
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=clasificacion
    )
    mocker.patch("app.agents.llm.get_llm_intake", return_value=mock_llm)


def _estado(mensaje: str) -> dict:
    return {
        "mensaje": mensaje,
        "canal": "whatsapp",
        "identificador": "+5491100000000",
        "historial": [],
    }


async def test_nodo_intake_clasifica_reclamo(mocker, db_session):
    _mock_intake(
        mocker,
        ClasificacionIntent(
            intencion="reclamo",
            entidades={"categoria": "infraestructura"},
            confianza=0.9,
        ),
    )

    resultado = await nodo_intake(_estado("La vereda de mi barrio está rota"), db_session)

    assert resultado["intencion"] == "reclamo"
    assert resultado["confianza"] >= 0.6
    assert resultado["requiere_escalado"] is False
    assert resultado["entidades"] == {"categoria": "infraestructura"}


async def test_nodo_intake_marca_pedido_de_humano(mocker, db_session):
    _mock_intake(
        mocker,
        ClasificacionIntent(
            intencion="otro", entidades={}, confianza=0.8, requiere_humano=True
        ),
    )

    resultado = await nodo_intake(_estado("Quiero hablar con una persona"), db_session)

    assert resultado["requiere_escalado"] is True
    assert resultado["motivo_escalado"] == "solicita_humano"


async def test_el_aviso_de_escalado_no_entra_al_historial_del_intake(
    db_session, mocker, ciudadano
):
    """Si ese texto entra, el clasificador lee "derivado a un operador" y marca
    requiere_humano en todos los mensajes siguientes: el caso escala en bucle."""
    from app.agents.escalado import RESPUESTA_ESCALADO
    from app.agents.intake import _historial_del_caso
    from app.db.crud.casos import crear_caso
    from app.db.crud.interacciones import crear_interaccion
    from app.db.models import ActorInteraccion, Canal, TipoCaso
    from app.schemas.caso import CasoCreate

    caso = await crear_caso(
        db_session,
        CasoCreate(
            ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo, canal_origen=Canal.email
        ),
        actor="test",
    )
    for contenido, actor in (
        ("Se cortó el agua en mi cuadra", ActorInteraccion.ciudadano),
        (RESPUESTA_ESCALADO, ActorInteraccion.agente_ia),
    ):
        await crear_interaccion(
            db_session, caso_id=caso.id, contenido=contenido, canal=Canal.email, actor=actor
        )
    await db_session.commit()

    historial = await _historial_del_caso(
        {"canal": "email", "identificador": ciudadano.email}, db_session
    )

    contenidos = [h["contenido"] for h in historial]
    assert "Se cortó el agua en mi cuadra" in contenidos
    assert RESPUESTA_ESCALADO not in contenidos


async def test_un_tema_nuevo_no_se_pega_al_caso_abierto(db_session, mocker, ciudadano):
    """Un vecino puede tener un reclamo en curso y preguntar por otra cosa: esa
    consulta merece su propio caso, no colgarse del reclamo."""
    from app.agents.contexto import nodo_contexto
    from app.db.crud.casos import crear_caso
    from app.db.models import Canal, TipoCaso
    from app.schemas.caso import CasoCreate

    abierto = await crear_caso(
        db_session,
        CasoCreate(
            ciudadano_id=ciudadano.id, tipo=TipoCaso.reclamo, canal_origen=Canal.email
        ),
        actor="test",
    )
    await db_session.commit()

    base = {
        "canal": "email",
        "identificador": ciudadano.email,
        "mensaje": "¿Dónde es el festival del queso?",
        "intencion": "consulta",
    }

    continuacion = await nodo_contexto({**base, "continua_caso_abierto": True}, db_session)
    tema_nuevo = await nodo_contexto({**base, "continua_caso_abierto": False}, db_session)

    assert continuacion["caso_id"] == str(abierto.id)
    assert tema_nuevo["caso_id"] is None
    assert tema_nuevo["historial"] == []
