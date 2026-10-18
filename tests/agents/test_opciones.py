"""El menú de inicio y la repregunta antes de derivar.

Dos cosas que se probaron por separado y se rompen juntas: que un mensaje sin
definir no abra caso (etiquetarlo sería adivinar, y el default es "consulta")
y que la repregunta tenga tope sin quedarse pegada.
"""

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.graph import procesar_mensaje
from app.agents.opciones import RESPUESTA_OPCIONES
from app.agents.saludo import MENU, TITULO_MAX, titulo_de_caso
from app.db.crud.interacciones import crear_interaccion
from app.db.models import (
    ActorInteraccion,
    Canal,
    Caso,
    EstadoCaso,
    TipoCaso,
)
from app.schemas.agente import ClasificacionIntent

SIN_DEFINIR = ClasificacionIntent(intencion="otro", entidades={}, confianza=0.3)
SALUDO = ClasificacionIntent(
    intencion="saludo", entidades={}, confianza=0.98, continua_caso_abierto=False
)


async def test_el_saludo_ofrece_las_tres_opciones(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms(SALUDO)

    final = await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    for opcion in ("Reclamo", "Consulta", "Trámite"):
        assert opcion in final["respuesta"]
    assert final["caso_id"] is None


async def test_el_saludo_enumera_los_pedidos_en_curso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """Para que pueda retomar uno en vez de abrir otro por lo mismo."""
    en_curso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.en_progreso,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    cerrado = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.cerrado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add_all([en_curso, cerrado])
    await db_session.commit()

    mock_llms(SALUDO)

    final = await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert en_curso.referencia in final["respuesta"]
    assert cerrado.referencia not in final["respuesta"], "un caso cerrado no se retoma"


async def test_sin_definir_no_abre_caso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El bug que motivó todo esto: "reportar un perro perdido" salía como
    "otro" y el caso se creaba igual, etiquetado "consulta" por defecto."""
    mock_llms(SIN_DEFINIR)

    final = await procesar_mensaje(
        db_session,
        mensaje="che una cosa",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"] == RESPUESTA_OPCIONES
    assert final["caso_id"] is None

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert casos == []


async def test_el_contador_de_repreguntas_se_reinicia_al_entender(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El contador vive en el checkpointer del hilo provisional, que el
    ciudadano reusa cada vez que arranca sin caso abierto. Si no se reiniciara,
    dos repreguntas de hace una semana lo dejarían derivando al primer mensaje
    para siempre."""
    mock_llms([SIN_DEFINIR, SIN_DEFINIR, SALUDO, SIN_DEFINIR])

    async def _mandar(texto: str):
        return await procesar_mensaje(
            db_session,
            mensaje=texto,
            canal=Canal.whatsapp,
            identificador=ciudadano.telefono,
            checkpointer=checkpointer_en_memoria,
        )

    assert (await _mandar("che"))["respuesta"] == RESPUESTA_OPCIONES
    assert (await _mandar("una cosa"))["respuesta"] == RESPUESTA_OPCIONES

    # Un mensaje que sí se entiende (acá, un saludo) borra la cuenta.
    assert MENU in (await _mandar("Hola"))["respuesta"]

    # Y por lo tanto vuelve a haber margen para preguntar en vez de derivar.
    ultima = await _mandar("otra cosa rara")
    assert ultima["respuesta"] == RESPUESTA_OPCIONES
    assert ultima["requiere_escalado"] is False


async def test_agotadas_las_vueltas_interviene_una_persona(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    mock_llms([SIN_DEFINIR, SIN_DEFINIR, SIN_DEFINIR])

    async def _mandar(texto: str):
        return await procesar_mensaje(
            db_session,
            mensaje=texto,
            canal=Canal.whatsapp,
            identificador=ciudadano.telefono,
            checkpointer=checkpointer_en_memoria,
        )

    await _mandar("che")
    await _mandar("una cosa")
    final = await _mandar("no sé cómo explicarlo")

    assert final["requiere_escalado"] is True
    assert final["caso_id"] is not None, "al derivar sí se abre caso: lo toma una persona"


def _caso(ciudadano_id, *, asunto=None, tipo=TipoCaso.reclamo) -> Caso:
    return Caso(
        ciudadano_id=ciudadano_id,
        tipo=tipo,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
        asunto=asunto,
    )


def test_el_titulo_sale_del_asunto_cuando_lo_hay(ciudadano):
    """En los casos por correo el asunto lo escribió el propio ciudadano."""
    caso = _caso(ciudadano.id, asunto="Pozo en la vereda de Agüero")

    assert titulo_de_caso(caso, "otra cosa que dijo después") == "Pozo en la vereda de Agüero"


def test_sin_asunto_el_titulo_son_las_primeras_palabras_del_ciudadano(ciudadano):
    caso = _caso(ciudadano.id)

    titulo = titulo_de_caso(caso, "Hay un pozo enorme en Agüero al 1200")

    assert titulo == "Hay un pozo enorme en Agüero al 1200"


def test_un_mensaje_largo_se_recorta_en_una_palabra_entera(ciudadano):
    caso = _caso(ciudadano.id)
    mensaje = (
        "Buenas tardes, quería reportar que hace más de dos semanas que "
        "hay un pozo enorme en la vereda de Agüero al 1200 y ya casi me caigo"
    )

    titulo = titulo_de_caso(caso, mensaje)

    assert len(titulo) <= TITULO_MAX + 1  # el carácter de puntos suspensivos
    assert titulo.endswith("…")
    assert "  " not in titulo
    assert titulo[:-1].strip() == titulo[:-1], "no corta a mitad de palabra"


def test_un_caso_sin_asunto_ni_mensajes_cae_en_el_tipo(ciudadano):
    """Un caso que abrió un operador desde el panel no tiene ninguna de las dos."""
    caso = _caso(ciudadano.id, tipo=TipoCaso.tramite)

    assert titulo_de_caso(caso, None) == "Tramite"


async def test_el_saludo_titula_cada_pedido_en_curso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """La referencia sola no sirve: nadie se acuerda de qué era REC-A6961E4A."""
    caso = _caso(ciudadano.id)
    db_session.add(caso)
    await db_session.flush()
    await crear_interaccion(
        db_session,
        caso_id=caso.id,
        contenido="Hay un pozo enorme en Agüero al 1200",
        canal=Canal.whatsapp,
        actor=ActorInteraccion.ciudadano,
    )
    await db_session.commit()

    mock_llms(SALUDO)

    final = await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    # Numerado a continuación del menú (1, 2 y 3 son los tipos) y con título.
    assert "4. Hay un pozo enorme en Agüero al 1200" in final["respuesta"]
    assert caso.referencia in final["respuesta"]
