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
    return {"mensaje": mensaje, "canal": "whatsapp", "historial": []}


async def test_nodo_intake_clasifica_reclamo(mocker):
    _mock_intake(
        mocker,
        ClasificacionIntent(
            intencion="reclamo",
            entidades={"categoria": "infraestructura"},
            confianza=0.9,
        ),
    )

    resultado = await nodo_intake(_estado("La vereda de mi barrio está rota"))

    assert resultado["intencion"] == "reclamo"
    assert resultado["confianza"] >= 0.6
    assert resultado["requiere_escalado"] is False
    assert resultado["entidades"] == {"categoria": "infraestructura"}


async def test_nodo_intake_marca_pedido_de_humano(mocker):
    _mock_intake(
        mocker,
        ClasificacionIntent(
            intencion="otro", entidades={}, confianza=0.8, requiere_humano=True
        ),
    )

    resultado = await nodo_intake(_estado("Quiero hablar con una persona"))

    assert resultado["requiere_escalado"] is True
    assert resultado["motivo_escalado"] == "solicita_humano"
