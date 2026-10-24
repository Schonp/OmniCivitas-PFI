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
        "vueltas_sin_definir": 0,
    }
    base.update(overrides)
    return base


def test_routing_pregunta_en_vez_de_escalar_con_confianza_baja():
    """Molestar a un operador porque el clasificador no entendió un mensaje
    ambiguo es caro e innecesario: lo que haría cualquiera es preguntar."""
    assert decidir_ruta(_estado(confianza=0.3)) == "opciones"


def test_routing_escala_cuando_se_agotan_las_repreguntas():
    """El que no logra explicarse con el agente es el que necesita una persona."""
    agotado = _estado(confianza=0.3, vueltas_sin_definir=2)
    assert decidir_ruta(agotado) == "escalado"


def test_routing_escala_si_requiere_escalado():
    assert decidir_ruta(_estado(requiere_escalado=True)) == "escalado"


def test_routing_pregunta_ante_intencion_otro():
    """"otro" no es un tipo de caso: abrir uno igual lo etiqueta "consulta" por
    defecto, que es como los reclamos terminaban mal clasificados."""
    assert decidir_ruta(_estado(intencion="otro")) == "opciones"


def test_routing_escala_tramite_sin_tool():
    assert decidir_ruta(_estado(intencion="tramite")) == "escalado"


def test_routing_escala_ciudadano_no_identificado():
    assert decidir_ruta(_estado(ciudadano_id=None)) == "escalado"


def test_routing_camino_feliz_va_a_ejecutor():
    assert decidir_ruta(_estado()) == "ejecutor"


def test_pedir_un_humano_gana_sobre_el_saludo():
    """El clasificador llegó a etiquetar "quisiera hablar con un operador" como
    saludo. Si el ruteo confía en la etiqueta, el ciudadano que pide una persona
    recibe el "¿en qué puedo ayudarlo?" y nadie lo deriva."""
    assert decidir_ruta(_estado(intencion="saludo", requiere_escalado=True)) == "escalado"


def test_un_saludo_a_secas_sigue_yendo_a_saludo():
    assert decidir_ruta(_estado(intencion="saludo")) == "saludo"


def test_quien_no_esta_identificado_y_manda_su_dni_va_al_ejecutor():
    """Aunque el intake lo clasifique como trámite, que se deriva directo."""
    from app.agents.graph import decidir_ruta

    estado = {
        "mensaje": "Laura Prueba, 30.111.291",
        "intencion": "tramite",
        "confianza": 0.9,
        "requiere_escalado": False,
        "ciudadano_id": "c1",
        "identificado": False,
    }
    assert decidir_ruta(estado) == "ejecutor"
    # Ya identificado, un trámite sigue derivándose.
    assert decidir_ruta({**estado, "identificado": True}) == "escalado"

