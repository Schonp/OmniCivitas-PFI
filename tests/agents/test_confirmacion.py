from app.agents.confirmacion import agradecimiento, confirmacion
from app.agents.ejecutor import DERIVAR, _cierre_sin_modelo
from app.db.models import Canal

RECLAMO = (
    {"name": "crear_reclamo", "args": {"descripcion": "Cable de luz caído en Av. Warnes 797"}},
    {"referencia": "REC-1A2B3C4D", "categoria": "infraestructura"},
)
RESERVA = (
    {"name": "crear_reserva", "args": {"turno": "dni", "fecha_hora": "2026-12-01 12:00"}},
    {"referencia": "RES-9F8E7D6C", "turno": "DNI", "fecha_hora": "2026-12-01 12:00"},
)


def test_el_reclamo_se_confirma_con_la_referencia_real():
    texto = confirmacion(*RECLAMO[0].values(), RECLAMO[1], Canal.whatsapp)

    assert texto.startswith("Registré su reclamo por cable de luz caído en Av. Warnes 797.")
    assert "Número de caso: REC-1A2B3C4D" in texto
    assert "*" not in texto


def test_por_voz_el_seguimiento_se_avisa_por_whatsapp_y_sin_etiquetas():
    texto = confirmacion(*RECLAMO[0].values(), RECLAMO[1], Canal.voz)

    assert "REC-1A2B3C4D" in texto
    assert "WhatsApp" in texto
    assert "\n" not in texto


def test_la_reserva_usa_el_nombre_de_la_agenda_y_la_fecha_en_criollo():
    texto = confirmacion(*RESERVA[0].values(), RESERVA[1], Canal.whatsapp)

    assert "Le reservé el turno de DNI." in texto
    assert "Día y hora: martes 1 de diciembre, 12:00 h" in texto
    assert "Número de caso: RES-9F8E7D6C" in texto


def test_por_voz_la_hora_en_punto_se_dice_sin_los_minutos():
    texto = confirmacion(*RESERVA[0].values(), RESERVA[1], Canal.voz)

    assert "para el martes 1 de diciembre a las 12." in texto


def test_las_consultas_no_tienen_confirmacion_fija():
    assert confirmacion("consultar_estado_caso", {}, {"casos": []}, Canal.whatsapp) is None


def test_el_agradecimiento_usa_solo_el_primer_nombre():
    assert agradecimiento({"nombre": "marta ruiz"}) == "Gracias, Marta. "
    assert agradecimiento({}) == "Gracias. "


# --- Cuándo el ejecutor cierra sin volver a llamar al modelo ----------------


def test_un_reclamo_creado_cierra_el_turno_sin_el_modelo():
    assert _cierre_sin_modelo([RECLAMO], Canal.whatsapp).startswith("Registré su reclamo")


def test_si_se_identifico_en_el_mismo_mensaje_se_le_agradece():
    identidad = ({"name": "registrar_identidad", "args": {}}, {"nombre": "Marta Ruiz"})

    texto = _cierre_sin_modelo([identidad, RECLAMO], Canal.whatsapp)

    assert texto.startswith("Gracias, Marta. Registré su reclamo")


def test_una_derivacion_pasa_directo_al_escalado():
    derivacion = ({"name": "derivar_a_operador", "args": {"motivo": "x"}}, {"derivado": True})

    assert _cierre_sin_modelo([derivacion], Canal.whatsapp) == DERIVAR


def test_una_consulta_de_estado_la_sigue_redactando_el_modelo():
    consulta = ({"name": "consultar_estado_caso", "args": {}}, {"casos": []})

    assert _cierre_sin_modelo([consulta], Canal.whatsapp) is None


def test_solo_identificarse_no_cierra_el_turno():
    """Después de registrar nombre y DNI el modelo tiene que seguir con la gestión."""
    identidad = ({"name": "registrar_identidad", "args": {}}, {"nombre": "Marta Ruiz"})

    assert _cierre_sin_modelo([identidad], Canal.whatsapp) is None
