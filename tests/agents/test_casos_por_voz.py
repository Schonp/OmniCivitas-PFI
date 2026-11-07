"""Cómo se ofrecen y se eligen los casos abiertos en una llamada.

Pasó en una prueba: el saludo decía "Veo que tiene un pedido en curso: ¿quiere
seguir con ese o es algo nuevo?", el ciudadano contestaba "quiero hacer una
nueva gestión" y el agente lo derivaba a una persona (lo clasificaba como
trámite). Ahora el saludo enumera los casos por su título, la elección se
resuelve por código y "algo nuevo" se contesta preguntando qué necesita.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.eleccion import armar_ofertas_voz, resolver_voz
from app.agents.intake import nodo_intake, pide_algo_nuevo_sin_decir_que
from app.agents.opciones import RESPUESTA_ALGO_NUEVO
from app.agents.saludo import armar_saludo
from app.channels import voz
from app.db.models import Caso, Canal, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent

TELEFONO = "+5491133335555"
OFERTAS = [{"numero": 1, "caso_id": "caso-1"}, {"numero": 2, "caso_id": "caso-2"}]


@pytest.mark.parametrize(
    "dicho,numero",
    [
        ("Uno.", 1),
        ("El dos", 2),
        ("Sí, el primero.", 1),
        ("Quiero seguir con el segundo", 2),
        ("El número 2, por favor", 2),
    ],
)
def test_la_eleccion_hablada_se_resuelve_por_codigo(dicho, numero):
    assert resolver_voz(dicho, OFERTAS)["numero"] == numero


@pytest.mark.parametrize(
    "dicho", ["Quiero reservar un turno", "Tres", "Sí", "Hay un pozo en la cuadra dos"]
)
def test_lo_que_no_es_una_eleccion_no_elige_nada(dicho):
    assert resolver_voz(dicho, OFERTAS) is None


def test_con_un_solo_caso_alcanza_con_decir_que_sigue_con_ese():
    assert resolver_voz("Sí, sigamos con ese", OFERTAS[:1]) == OFERTAS[0]
    assert resolver_voz("Sí, ese", OFERTAS[:1]) == OFERTAS[0]


@pytest.mark.parametrize(
    "mensaje",
    [
        "Quiero hacer una nueva gestión.",
        "Hola, quiero hacer algo nuevo.",
        "Algo nuevo",
        "No, es algo nuevo.",
        "Otra cosa",
    ],
)
def test_reconoce_algo_nuevo_sin_contenido(mensaje):
    assert pide_algo_nuevo_sin_decir_que(mensaje)


@pytest.mark.parametrize(
    "mensaje",
    ["Quiero reservar un turno para la licencia", "Algo nuevo: hay un pozo en mi cuadra", "Hola"],
)
def test_si_dice_que_necesita_no_es_algo_nuevo_vacio(mensaje):
    assert not pide_algo_nuevo_sin_decir_que(mensaje)


def test_el_saludo_por_voz_enumera_los_casos_por_titulo():
    casos = [
        Caso(tipo=TipoCaso.reclamo, titulo="Pozo en Guatemala 4100"),
        Caso(tipo=TipoCaso.reserva, titulo="Licencia de conducir"),
    ]

    saludo = armar_saludo(casos, {}, [], canal=Canal.voz)

    assert "Tiene dos pedidos en curso: uno, reclamo por pozo en Guatemala 4100; dos, turno de licencia de conducir." in saludo
    assert "dígame el número" in saludo
    assert armar_ofertas_voz(casos)[1]["numero"] == 2


def test_el_saludo_siempre_recuerda_que_puede_pedir_eliminar_sus_datos():
    saludo = armar_saludo([], {}, [], canal=Canal.voz, primer_contacto=False)

    assert "eliminen sus datos" in saludo


def _mock_intake(mocker, clasificacion):
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=clasificacion)
    mocker.patch("app.agents.llm.get_llm_intake", return_value=llm)


def _estado_voz(mensaje: str, ofertas: list[dict]) -> dict:
    return {
        "mensaje": mensaje,
        "canal": "voz",
        "identificador": TELEFONO,
        "historial": [],
        "ofertas": ofertas,
    }


async def test_si_no_elige_un_caso_ofrecido_lo_que_cuenta_es_nuevo(mocker, db_session):
    _mock_intake(
        mocker,
        ClasificacionIntent(intencion="reserva", entidades={}, confianza=0.9, continua_caso_abierto=True),
    )

    resultado = await nodo_intake(_estado_voz("Quiero reservar un turno", OFERTAS), db_session)

    assert resultado["continua_caso_abierto"] is False
    assert resultado["ofertas"] == [], "las ofertas valen solo para la respuesta al saludo"


async def test_elegir_el_dos_retoma_ese_caso(db_session):
    resultado = await nodo_intake(_estado_voz("El dos", OFERTAS), db_session)

    assert resultado["caso_elegido"] == "caso-2"


async def test_algo_nuevo_pregunta_que_necesita_en_vez_de_derivar(
    db_session, mock_llms, checkpointer_en_memoria
):
    mock_llms(ClasificacionIntent(intencion="tramite", entidades={}, confianza=0.9))

    final = await voz.recibir_turno(
        db_session, telefono=TELEFONO, mensaje="Quiero hacer una nueva gestión."
    )

    assert final["respuesta"] == RESPUESTA_ALGO_NUEVO
    assert not final.get("requiere_escalado")
    casos = (await db_session.execute(select(Caso))).scalars().all()
    assert casos == [], "todavía no dijo qué necesita: no se abre caso"


async def test_el_reclamo_registrado_queda_con_titulo(db_session, ciudadano):
    from app.tools import reclamos

    salida = await reclamos.crear_reclamo(
        db_session,
        ciudadano_id=ciudadano.id,
        canal=Canal.voz,
        descripcion="Pozo en la calzada en Guatemala 4100",
        categoria="infraestructura",
    )

    caso = await db_session.get(Caso, uuid.UUID(salida["caso_id"]))
    assert caso.titulo == "Pozo en la calzada en Guatemala 4100"


async def test_solo_el_supervisor_cambia_el_titulo(client, auth_headers, headers_operador, ciudadano):
    creado = await client.post(
        "/api/casos",
        json={"ciudadano_id": str(ciudadano.id), "tipo": "reclamo", "canal_origen": "voz"},
        headers=auth_headers,
    )
    caso_id = creado.json()["id"]

    del_operador = await client.patch(
        f"/api/casos/{caso_id}/titulo", json={"titulo": "Otro"}, headers=headers_operador
    )
    del_supervisor = await client.patch(
        f"/api/casos/{caso_id}/titulo",
        json={"titulo": "  Pozo   en Guatemala 4100 "},
        headers=auth_headers,
    )

    assert del_operador.status_code == 403
    assert del_supervisor.status_code == 200
    assert del_supervisor.json()["titulo"] == "Pozo en Guatemala 4100"
    auditoria = await client.get(f"/api/casos/{caso_id}/auditoria", headers=auth_headers)
    assert any(evento["accion"] == "cambio_titulo" for evento in auditoria.json())
