"""Recuperación léxica de la base de conocimiento.

Antes ordenaba por fecha de carga, así que el documento correcto se caía del
contexto apenas la base crecía: solo entran MAX_DOCUMENTOS_CONTEXTO y cualquier
documento nuevo que compartiera una palabra suelta lo desplazaba.
"""

import pytest

from app.db.crud.conocimiento import (
    MAX_DOCUMENTOS_CONTEXTO,
    buscar_documentos_relevantes,
    crear_documento,
    palabras_significativas,
)


def _titulos(fragmentos: list[str]) -> list[str]:
    return [fragmento.split(":")[0] for fragmento in fragmentos]


# --- Selección de palabras -------------------------------------------------


def test_descarta_muletillas_y_palabras_cortas():
    assert palabras_significativas("Hola, necesito saber algo del turno") == {"turno"}


def test_un_saludo_no_deja_ninguna_palabra_buscable():
    assert palabras_significativas("Hola, buenas, gracias") == set()


def test_conserva_el_vocabulario_del_dominio():
    """"reclamo" y "turno" son muletillas del habla pero acá son el tema."""
    palabras = palabras_significativas("quiero hacer un reclamo por el alumbrado")
    assert palabras == {"reclamo", "alumbrado"}


def test_normaliza_acentos_y_mayusculas():
    assert palabras_significativas("ÁRBOL caído") == {"arbol", "caido"}


# --- Búsqueda --------------------------------------------------------------


async def test_gana_el_documento_que_menciona_mas_palabras(db_session):
    await crear_documento(
        db_session,
        titulo="Licencia de conducir por primera vez",
        contenido="La licencia inicial exige DNI y examen práctico.",
    )
    # Se carga después, así que por fecha iría primero; debe ganar igual el otro.
    await crear_documento(
        db_session,
        titulo="Renovar la licencia de conducir",
        contenido="Renovar la licencia exige la licencia anterior y el DNI.",
    )

    titulos = _titulos(
        await buscar_documentos_relevantes(db_session, "Necesito renovar mi licencia")
    )

    assert titulos[0] == "Renovar la licencia de conducir"


async def test_el_titulo_pesa_mas_que_el_contenido(db_session):
    await crear_documento(
        db_session, titulo="Poda de árboles", contenido="Ramas y arbolado."
    )
    await crear_documento(
        db_session,
        titulo="Sedes y horarios",
        contenido="Las sedes atienden de 8 a 15. También se reciben pedidos de poda.",
    )

    # Una sola palabra buscable ("quiero" es muletilla): el que la tiene en el
    # título gana al que solo la menciona en el cuerpo, aunque este sea más nuevo.
    titulos = _titulos(await buscar_documentos_relevantes(db_session, "quiero poda"))

    assert titulos[0] == "Poda de árboles"


async def test_encuentra_aunque_el_ciudadano_escriba_sin_tildes(db_session):
    await crear_documento(
        db_session,
        titulo="Alumbrado público",
        contenido="Luminarias apagadas o con el foco quemado.",
    )

    titulos = _titulos(
        await buscar_documentos_relevantes(db_session, "consulta por alumbrado publico")
    )

    assert titulos == ["Alumbrado público"]


async def test_un_saludo_no_recupera_nada(db_session):
    await crear_documento(
        db_session, titulo="Sedes y horarios", contenido="Atención de 8 a 15."
    )

    assert await buscar_documentos_relevantes(db_session, "Hola, buenas") == []


async def test_una_muletilla_compartida_no_arrastra_documentos(db_session):
    """El bug original: "para" estaba en un documento y lo recuperaba siempre."""
    await crear_documento(
        db_session,
        titulo="Requisitos para renovar la licencia",
        contenido="Necesita la licencia anterior para el trámite.",
    )

    assert await buscar_documentos_relevantes(db_session, "tengo una consulta") == []


async def test_respeta_el_tope_de_documentos(db_session):
    for i in range(MAX_DOCUMENTOS_CONTEXTO + 3):
        await crear_documento(
            db_session, titulo=f"Turnos sede {i}", contenido="Agenda de turnos."
        )

    assert len(await buscar_documentos_relevantes(db_session, "turnos")) == (
        MAX_DOCUMENTOS_CONTEXTO
    )


@pytest.mark.parametrize("mensaje", ["", "   ", "de la un"])
async def test_mensajes_sin_palabras_utiles(db_session, mensaje):
    await crear_documento(db_session, titulo="Sedes", contenido="Atención de 8 a 15.")

    assert await buscar_documentos_relevantes(db_session, mensaje) == []
