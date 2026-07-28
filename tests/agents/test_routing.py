from app.agents.graph import decidir_ruta


def _estado(**overrides) -> dict:
    base = {
        "mensaje": "hola",
        "canal": "whatsapp",
        "identificador": "+549112233",
        "ciudadano_id": "algun-uuid",
        "caso_id": None,
        "historial": [],
        "conocimiento": [],
        "intencion": "reclamo",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }
    base.update(overrides)
    return base


def test_routing_escala_con_confianza_baja():
    assert decidir_ruta(_estado(confianza=0.3)) == "escalado"


def test_routing_escala_si_requiere_escalado():
    assert decidir_ruta(_estado(requiere_escalado=True)) == "escalado"


def test_routing_escala_intencion_otro():
    assert decidir_ruta(_estado(intencion="otro")) == "escalado"


def test_routing_escala_tramite_sin_tool():
    assert decidir_ruta(_estado(intencion="tramite")) == "escalado"


def test_routing_escala_ciudadano_no_identificado():
    assert decidir_ruta(_estado(ciudadano_id=None)) == "escalado"


def test_routing_camino_feliz_va_a_ejecutor():
    assert decidir_ruta(_estado()) == "ejecutor"
