"""Arma el dataset de fine-tuning en el formato exacto en que la app usa el modelo.

El primer fine-tuning entrenó al modelo a devolver un único JSON (intención,
confianza, llamada a herramienta y respuesta) con un prompt propio y de un solo
turno. La aplicación no lo usa así: lo llama dos veces por mensaje, con otros
prompts, con herramientas nativas de Qwen e historial. Servido por Ollama, el
modelo rendía 91% de tool calling con el prompt del entrenamiento y 66% por el
camino de la app (ver DEVLOG.md, "Integración con Ollama").

Este script reescribe los mismos ejemplos, y agrega los que faltaban, como
conversaciones idénticas a las que arma la app. No copia los prompts: los
importa de `app/` y renderiza con la misma función que usa la inferencia
(`app.agents.llm.a_formato_qwen`), así que si un prompt cambia, el dataset
cambia con él.

Dos tipos de conversación:

- **intake**: el prompt de clasificación y, como respuesta, el JSON de
  `ClasificacionIntent`. Usa los ejemplos de MASSIVE/MULTI3NLU++ (submuestreados:
  son 13 mil y solo enseñan intención) más los manuales, saludos, pedidos de
  hablar con una persona y mensajes con historial.
- **ejecutor**: el prompt del ejecutor con las herramientas que ofrece la app
  para esa intención. Incluye lo que el primer dataset no tenía: varios turnos
  (pedir el dato que falta y recién ahí llamar), la respuesta a partir del
  resultado de `consultar_estado_caso`, `registrar_identidad` y
  `derivar_a_operador`.

Las confirmaciones de reclamos y reservas no se entrenan: las arma el código
(`app/agents/confirmacion.py`), así que la conversación termina en la llamada.

La tercera versión agrega las pautas generales del organismo
(`conocimiento/pautas_generales/`): aparecen en una parte de los prompts, igual
que en producción, y hay conversaciones donde aplicarlas cambia la respuesta
(una emergencia, un pedido de opinión política o de una clave). Las reservas
traen la grilla de cada agenda en la información del organismo, como la arma
hoy el agente de contexto.

La cuarta versión suma lo que falló con la v3 en conversaciones reales por
WhatsApp y correo: el reclamo después del pedido de datos (una sola llamada,
sin agregar calles que nadie dijo), la pregunta por su caso desde un contacto
sin identificar (se le piden los datos para buscarlo), la pregunta de
seguimiento ya identificado (se contesta con la información del organismo, sin
volver a pedir el DNI), "¿cómo va el reclamo?" como consulta en el intake, y
más emergencias por gas y de violencia. Las respuestas que el código ya arma
(los avisos, los pedidos de datos) se importan de `app/`: el modelo aprende el
mismo texto que usa la red de seguridad.

Uso, desde la raíz del repo con las dependencias de la app instaladas y después
de `finetuning/armar_dataset.py`:

    python -m finetuning.armar_dataset_app

Salida en finetuning/data/: app_train.jsonl, app_validacion.jsonl y
app_prueba.jsonl (el conjunto de prueba de tool calling en este formato, para
la celda de evaluación del notebook).
"""

import json
import random
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents.confirmacion import pedido_de_identificacion, pedido_de_identificacion_para_consulta
from app.agents.ejecutor import NO_TENGO_ESE_DATO, construir_tools, prompt_del_sistema
from app.agents.seguridad import aviso_de_seguridad
from scripts.archivos_conocimiento import CARPETA_CONOCIMIENTO, leer_carpeta
from scripts.documentos_de_ejemplo import DOCUMENTOS
from app.agents.intake import SYSTEM_INTAKE, _formatear_historial
from app.agents.llm import a_formato_qwen
from app.db.models import Canal

DATA = Path(__file__).parent / "data"
SEMILLA = 2026
# MASSIVE + MULTI3NLU++ son el 98% del dataset original y solo enseñan
# intención. Todos juntos, con prompts de ~800 tokens, llevarían el
# entrenamiento a más de 10 horas en la GPU gratuita de Colab.
MAX_INTAKE_EXTERNOS = 1600
PROPORCION_VALIDACION = 0.1
# Fecha desde la que se escribieron los ejemplos manuales con fecha fija
# (noviembre y diciembre de 2026). La misma usa scripts/evaluar_modelo_local.py.
HOY_DEL_DATASET = datetime(2026, 10, 19)

random.seed(SEMILLA)

# Las pautas tal como las arma `listar_pautas_generales` para el prompt.
PAUTAS = [
    f"{titulo}: {contenido}"
    for titulo, contenido, _ in leer_carpeta(CARPETA_CONOCIMIENTO / "pautas_generales")
]
# En producción un organismo puede no tener pautas cargadas: el modelo tiene que
# andar igual con el bloque y sin él.
PROPORCION_CON_PAUTAS = 0.4
_AL_AZAR = object()

# La información de turnos que suma el agente de contexto cuando la intención
# es una reserva (ver `buscar_conocimiento`).
CONOCIMIENTO_TURNOS = [
    "Turnos disponibles para reservar: CeSAC; DNI; licencia de conducir",
    "Horarios de atención: CeSAC, de lunes a viernes de 9:00 a 15:00, cada 30 minutos; "
    "DNI, de lunes a viernes de 8:00 a 13:00, cada 20 minutos; licencia de conducir, de "
    "lunes a viernes de 8:00 a 14:00, cada 30 minutos",
]


# --- Render ------------------------------------------------------------------


def _rol(mensaje: BaseMessage) -> str:
    if isinstance(mensaje, SystemMessage):
        return "system"
    if isinstance(mensaje, HumanMessage):
        return "user"
    return "assistant"


def _tools(intencion: str, identificado: bool = True) -> list[dict]:
    estado = {
        "ciudadano_id": str(uuid.uuid4()),
        "canal": "whatsapp",
        "intencion": intencion,
        "identificado": identificado,
    }
    return [convert_to_openai_tool(t) for t in construir_tools(None, estado)]


def _render(mensajes: list[BaseMessage], tools: list[dict]) -> list[dict]:
    return [
        {"role": _rol(m), "content": str(m.content)} for m in a_formato_qwen(mensajes, tools)
    ]


def _llamada(nombre: str, args: dict) -> dict:
    return {"name": nombre, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def _canal_ejecutor() -> Canal:
    return Canal.voz if random.random() < 0.2 else Canal.whatsapp


def conversacion_ejecutor(
    turnos: list[BaseMessage],
    *,
    intencion: str,
    canal: Canal | None = None,
    identificado: bool = True,
    conocimiento: list[str] | None = None,
    origen_menu: str | None = None,
    hoy: datetime = HOY_DEL_DATASET,
    pautas=_AL_AZAR,
) -> dict:
    canal = canal or _canal_ejecutor()
    if pautas is _AL_AZAR:
        pautas = PAUTAS if random.random() < PROPORCION_CON_PAUTAS else None
    sistema = prompt_del_sistema(
        canal,
        conocimiento=conocimiento,
        pautas=pautas,
        origen_menu=origen_menu,
        identificado=identificado,
        hoy=hoy,
    )
    tools = _tools(intencion, identificado)
    return {
        "tipo": "ejecutor",
        "messages": _render([SystemMessage(content=sistema), *turnos], tools),
    }


def conversacion_intake(
    mensaje: str,
    *,
    intencion: str,
    confianza: float,
    entidades: dict | None = None,
    continua: bool = True,
    requiere_humano: bool = False,
    historial: list[dict] | None = None,
    canal: str | None = None,
) -> dict:
    canal = canal or random.choices(["whatsapp", "email", "voz"], [0.7, 0.15, 0.15])[0]
    usuario = _formatear_historial(historial or []) + (
        f"Mensaje del ciudadano (canal {canal}): {mensaje}"
    )
    # Mismo orden de campos que el esquema de ClasificacionIntent, que es el
    # orden en que Ollama fuerza la salida estructurada.
    salida = {
        "intencion": intencion,
        "entidades": entidades or {},
        "confianza": confianza,
        "continua_caso_abierto": continua,
        "requiere_humano": requiere_humano,
    }
    return {
        "tipo": "intake",
        "messages": [
            {"role": "system", "content": SYSTEM_INTAKE},
            {"role": "user", "content": usuario},
            {"role": "assistant", "content": json.dumps(salida, ensure_ascii=False)},
        ],
    }


# --- Bancos para los ejemplos nuevos ----------------------------------------

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
TURNOS = ["DNI", "licencia de conducir", "CeSAC"]
NOMBRES = [
    "Marta Ruiz", "Carlos Gómez", "Lucía Fernández", "Jorge Pereyra", "Ana Sosa",
    "Diego Romero", "Valeria Medina", "Héctor Acosta", "Paula Benítez", "Raúl Herrera",
    "Silvia Castro", "Martín Aguirre", "Graciela Ríos", "Nicolás Vera", "Rosa Molina",
]
CALLES = [
    "Av. Rivadavia", "Av. Corrientes", "Av. Cabildo", "Av. Directorio", "Humboldt",
    "Thames", "Honduras", "Gurruchaga", "Serrano", "Medrano", "Av. Boedo", "Soler",
]
RECLAMOS_INCOMPLETOS = [
    ("hay un pozo enorme en la calle", "Pozo en la calzada", "infraestructura"),
    ("se cayó un árbol en la vereda", "Árbol caído en la vereda", "infraestructura"),
    ("hay un poste de luz quemado", "Poste de luz quemado", "infraestructura"),
    ("el semáforo no funciona", "Semáforo fuera de servicio", "infraestructura"),
    ("se rompió un caño y sale agua", "Pérdida de agua en la calzada", "infraestructura"),
    ("no pasa el camión de la basura hace días", "No pasa el camión de recolección de basura", "servicio"),
    ("no barren la cuadra hace semanas", "Falta de barrido en la cuadra", "servicio"),
    ("los contenedores están desbordados", "Contenedores de basura desbordados", "servicio"),
    ("hay ruidos de una obra fuera de horario", "Ruidos molestos de obra fuera de horario", "servicio"),
]
VAGOS = ["cerca de mi casa", "en mi cuadra", "en mi calle", "en el barrio"]
PIDE_DIRECCION = [
    "Para registrar el reclamo necesito la dirección exacta. ¿Me la puede indicar?",
    "¿Me puede pasar la calle y la altura? Así registro el reclamo.",
]
PIDE_FECHA = [
    "¿Qué día y a qué hora le queda bien para el turno de {turno}?",
    "Claro. ¿Para qué día y horario quiere el turno de {turno}?",
]
PEDIDOS_HUMANO = [
    "Quiero hablar con una persona",
    "¿Me pasás con un operador?",
    "Prefiero que me atienda alguien de carne y hueso",
    "Necesito hablar con un humano, no con un bot",
    "¿Hay alguien del organismo que me pueda atender?",
    "Pasame con alguien que me pueda ayudar de verdad",
    "Quiero que me llame una persona del organismo",
    "No quiero hablar con una máquina, quiero un empleado",
]
SALUDOS = [
    "hola", "Hola!", "buenas", "Buen día", "Buenas tardes", "buenas noches",
    "gracias", "Muchas gracias!", "ok gracias", "estás ahí?", "Hola, ¿cómo va?",
    "Hola buenas", "Que tal", "Buenas, ¿hay alguien?", "Gracias, muy amable",
]
ESTADO_EN_PALABRAS = {
    "abierto": "está registrado y pendiente de que el área lo tome",
    "en_progreso": "está en curso: el área ya lo está trabajando",
    "escalado": "lo está revisando una persona del organismo",
    "cerrado": "ya está cerrado",
}


def _fecha_futura(hoy: datetime) -> tuple[str, str]:
    """Un día hábil futuro dicho como lo diría un vecino, y su AAAA-MM-DD HH:MM."""
    while True:
        dia = hoy + timedelta(days=random.randint(1, 40))
        if dia.weekday() < 5:
            break
    hora, minuto = random.choice([(8, 0), (9, 30), (10, 0), (10, 15), (11, 0), (12, 0), (13, 30), (15, 0)])
    iso = f"{dia:%Y-%m-%d} {hora:02d}:{minuto:02d}"
    hablada = f"{hora}" if minuto == 0 else f"{hora}:{minuto:02d}"
    formas = [
        f"el {DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]} a las {hablada}",
        f"el {dia.day} de {MESES[dia.month - 1]} a las {hablada}",
        f"{dia.day}/{dia.month} a las {hablada}",
    ]
    if (dia - hoy).days < 7 and dia.weekday() > hoy.weekday():
        formas.append(f"este {DIAS[dia.weekday()]} a las {hablada}")
    return random.choice(formas), iso


def _hoy_al_azar() -> datetime:
    return datetime(2026, 1, 5) + timedelta(days=random.randint(0, 700))


def _referencia(prefijo: str) -> str:
    return f"{prefijo}-{uuid.uuid4().hex[:8].upper()}"


def _dni() -> tuple[str, str]:
    numero = str(random.randint(20_000_000, 45_000_000))
    con_puntos = f"{numero[:2]}.{numero[2:5]}.{numero[5:]}"
    return random.choice([numero, con_puntos]), numero


# --- Conversión del dataset existente ----------------------------------------

RESPUESTAS_QUE_DERIVAN = re.compile(r"derivé|derivado", re.IGNORECASE)
PIDE_HUMANO = re.compile(r"\b(humano|persona|operador)\b", re.IGNORECASE)


def ejecutor_desde_ejemplo(ejemplo: dict) -> dict | None:
    """Un ejemplo manual del dataset original, como conversación del ejecutor."""
    instruccion = ejemplo["instruccion"]
    intencion = ejemplo["intencion"]
    llamada = ejemplo.get("llamada_herramienta")
    respuesta = ejemplo.get("respuesta")

    if llamada:
        turnos: list[BaseMessage] = [
            HumanMessage(content=instruccion),
            AIMessage(content="", tool_calls=[_llamada(llamada["nombre"], llamada["parametros"])]),
        ]
        return conversacion_ejecutor(turnos, intencion=intencion)

    if not respuesta:
        return None
    if PIDE_HUMANO.search(instruccion) or (
        intencion == "tramite" and RESPUESTAS_QUE_DERIVAN.search(respuesta)
    ):
        # En la app un trámite no tiene herramienta propia: se deriva con
        # `derivar_a_operador` y el aviso al ciudadano lo arma el escalado.
        motivo = f"El ciudadano necesita: {instruccion.rstrip('.?!')}"
        turnos = [
            HumanMessage(content=instruccion),
            AIMessage(content="", tool_calls=[_llamada("derivar_a_operador", {"motivo": motivo})]),
        ]
        return conversacion_ejecutor(turnos, intencion=intencion)

    conocimiento = None
    if intencion == "consulta" and "?" not in respuesta:
        # La respuesta informativa tiene que salir de la información del
        # organismo que trae la app, nunca de memoria: se entrena con el dato
        # presente en el prompt para no enseñarle a inventar requisitos.
        conocimiento = [f"- {respuesta}"]
    turnos = [HumanMessage(content=instruccion), AIMessage(content=respuesta)]
    return conversacion_ejecutor(turnos, intencion=intencion, conocimiento=conocimiento)


def intake_desde_ejemplo(ejemplo: dict) -> dict:
    llamada = ejemplo.get("llamada_herramienta") or {}
    entidades = {}
    categoria = (llamada.get("parametros") or {}).get("categoria")
    if categoria:
        entidades["categoria"] = categoria
    return conversacion_intake(
        ejemplo["instruccion"],
        intencion=ejemplo["intencion"],
        confianza=ejemplo["confianza"],
        entidades=entidades,
        requiere_humano=bool(PIDE_HUMANO.search(ejemplo["instruccion"])),
    )


# --- Ejemplos nuevos ---------------------------------------------------------


def reclamos_en_dos_turnos(n: int) -> list[dict]:
    salida = []
    for _ in range(n):
        frase, formal, categoria = random.choice(RECLAMOS_INCOMPLETOS)
        direccion = f"{random.choice(CALLES)} {random.randint(100, 5000)}"
        respuesta_direccion = random.choice([direccion, f"Es en {direccion}", f"En {direccion}, gracias"])
        turnos = [
            HumanMessage(content=f"{frase.capitalize()} {random.choice(VAGOS)}"),
            AIMessage(content=random.choice(PIDE_DIRECCION)),
            HumanMessage(content=respuesta_direccion),
            AIMessage(
                content="",
                tool_calls=[
                    _llamada(
                        "crear_reclamo",
                        {"descripcion": f"{formal} en {direccion}", "categoria": categoria},
                    )
                ],
            ),
        ]
        salida.append(conversacion_ejecutor(turnos, intencion="reclamo"))
    return salida


def reservas(n_completas: int, n_dos_turnos: int) -> list[dict]:
    salida = []
    for _ in range(n_completas):
        hoy = _hoy_al_azar()
        turno = random.choice(TURNOS)
        dicha, iso = _fecha_futura(hoy)
        pedido = random.choice([
            "Necesito un turno de {t} para {f}", "Quiero sacar turno para {t}, {f}",
            "¿Me dan un turno de {t} {f}?", "Turno de {t} para {f} por favor",
        ]).format(t=turno, f=dicha)
        turnos = [
            HumanMessage(content=pedido),
            AIMessage(content="", tool_calls=[_llamada("crear_reserva", {"turno": turno, "fecha_hora": iso})]),
        ]
        salida.append(
            conversacion_ejecutor(turnos, intencion="reserva", hoy=hoy, conocimiento=CONOCIMIENTO_TURNOS)
        )
    for _ in range(n_dos_turnos):
        hoy = _hoy_al_azar()
        turno = random.choice(TURNOS)
        dicha, iso = _fecha_futura(hoy)
        turnos = [
            HumanMessage(content=random.choice([
                "Quiero sacar un turno de {t}", "Necesito turno para {t}", "Hola, quería un turno de {t}",
            ]).format(t=turno)),
            AIMessage(content=random.choice(PIDE_FECHA).format(turno=turno)),
            HumanMessage(content=random.choice(["{f}", "Puede ser {f}", "Me queda bien {f}"]).format(f=dicha)),
            AIMessage(content="", tool_calls=[_llamada("crear_reserva", {"turno": turno, "fecha_hora": iso})]),
        ]
        salida.append(
            conversacion_ejecutor(turnos, intencion="reserva", hoy=hoy, conocimiento=CONOCIMIENTO_TURNOS)
        )
    return salida


def _caso(tipo: str, de_que_trata: str, estado: str) -> dict:
    prefijo = {"reclamo": "REC", "reserva": "RES", "tramite": "TRA", "consulta": "CON"}[tipo]
    return {
        "referencia": _referencia(prefijo),
        "tipo": tipo,
        "estado": estado,
        "actualizado": "2026-10-15T14:32:00+00:00",
        "de_que_trata": de_que_trata,
    }


CASOS_POSIBLES = [
    ("reclamo", "Hay un árbol caído en Thames 1200"),
    ("reclamo", "No pasa el camión de la basura hace una semana"),
    ("reclamo", "El semáforo de Cabildo y Juramento no anda"),
    ("reserva", "Turno de DNI"),
    ("reserva", "Turno de licencia de conducir"),
    ("tramite", "Habilitación de un local comercial"),
]


def consultas_de_estado(n: int) -> list[dict]:
    salida = []
    for _ in range(n):
        escenario = random.choices(["uno", "varios", "ninguno"], [0.6, 0.3, 0.1])[0]
        pregunta = random.choice([
            "¿Cómo va mi reclamo?", "¿En qué quedó lo que pedí?", "Quiero saber cómo sigue mi caso",
            "¿Tienen novedades?", "¿Cómo viene mi trámite?",
        ])
        llamada = _llamada("consultar_estado_caso", {"referencia": ""})
        if escenario == "ninguno":
            resultado = {"tiene_casos": False, "mensaje": "El ciudadano no tiene casos registrados."}
            final = "No encontré casos a su nombre. ¿Quiere contarme qué necesita para registrarlo?"
        elif escenario == "uno":
            tipo, de_que = random.choice(CASOS_POSIBLES)
            caso = _caso(tipo, de_que, random.choice(list(ESTADO_EN_PALABRAS)))
            resultado = {"tiene_casos": True, "coincidio_la_pista": False, "varios_posibles": False, **caso}
            final = (
                f"Su {tipo} por \"{de_que}\" {ESTADO_EN_PALABRAS[caso['estado']]}.\n\n"
                f"Número de caso: {caso['referencia']}"
            )
        else:
            elegidos = random.sample(CASOS_POSIBLES, 2)
            casos = [_caso(t, d, random.choice(["abierto", "en_progreso"])) for t, d in elegidos]
            resultado = {"tiene_casos": True, "coincidio_la_pista": False, "varios_posibles": True, "casos": casos}
            lista = " y ".join(f"\"{c['de_que_trata']}\" ({c['referencia']})" for c in casos)
            final = f"Tiene más de un caso en curso: {lista}. ¿Por cuál me consulta?"
        turnos = [
            HumanMessage(content=pregunta),
            AIMessage(content="", tool_calls=[llamada]),
            ToolMessage(content=json.dumps(resultado, ensure_ascii=False), tool_call_id=llamada["id"]),
            AIMessage(content=final),
        ]
        salida.append(conversacion_ejecutor(turnos, intencion="consulta", canal=Canal.whatsapp))
    return salida


def identificaciones(n: int) -> list[dict]:
    salida = []
    for _ in range(n):
        nombre = random.choice(NOMBRES)
        dicho, numero = _dni()
        registrar = _llamada("registrar_identidad", {"nombre_completo": nombre, "documento": numero})
        resultado = json.dumps(
            {"identificado": True, "nombre": nombre, "documento": numero}, ensure_ascii=False
        )
        escenario = random.choice(["solo", "con_reclamo", "respuesta_al_pedido"])
        if escenario == "solo":
            turnos = [
                HumanMessage(content=random.choice(["Soy {n}, DNI {d}", "Mi nombre es {n} y mi DNI es {d}"]).format(n=nombre, d=dicho)),
                AIMessage(content="", tool_calls=[registrar]),
                ToolMessage(content=resultado, tool_call_id=registrar["id"]),
                AIMessage(content=f"Gracias, {nombre.split()[0]}. ¿En qué lo puedo ayudar?"),
            ]
            intencion = "otro"
        else:
            frase, formal, categoria = random.choice(RECLAMOS_INCOMPLETOS)
            direccion = f"{random.choice(CALLES)} {random.randint(100, 5000)}"
            reclamo = _llamada(
                "crear_reclamo", {"descripcion": f"{formal} en {direccion}", "categoria": categoria}
            )
            if escenario == "con_reclamo":
                turnos = [
                    HumanMessage(content=f"Soy {nombre}, DNI {dicho}. {frase.capitalize()} en {direccion}"),
                    AIMessage(content="", tool_calls=[registrar, reclamo]),
                ]
            else:
                turnos = [
                    HumanMessage(content=f"{frase.capitalize()} en {direccion}"),
                    AIMessage(content=(
                        "Hola, le escribe la atención ciudadana del organismo. Tomé nota de su "
                        f"reclamo por {formal.lower()} en {direccion}. Para registrarlo a su nombre "
                        "necesito su nombre completo y su DNI."
                    )),
                    HumanMessage(content=f"{nombre}, {dicho}"),
                    AIMessage(content="", tool_calls=[registrar]),
                    ToolMessage(content=resultado, tool_call_id=registrar["id"]),
                    AIMessage(content="", tool_calls=[reclamo]),
                ]
            intencion = "reclamo"
        salida.append(conversacion_ejecutor(turnos, intencion=intencion, identificado=False, canal=Canal.whatsapp))
    return salida


def pedidos_de_humano() -> list[dict]:
    salida = []
    for pedido in PEDIDOS_HUMANO:
        derivar = _llamada("derivar_a_operador", {"motivo": "El ciudadano pide hablar con una persona"})
        turnos = [HumanMessage(content=pedido), AIMessage(content="", tool_calls=[derivar])]
        salida.append(conversacion_ejecutor(turnos, intencion="consulta"))
    return salida


def elecciones_de_menu() -> list[dict]:
    salida = []
    for numero, tipo, pregunta in [
        ("1", "reclamo", "Cuénteme qué problema quiere reportar y en qué dirección es."),
        ("2", "reserva", "¿Para qué trámite necesita el turno y qué día le queda bien?"),
        ("3", "consulta", "¿Qué quiere consultar?"),
    ]:
        for _ in range(4):
            turnos = [HumanMessage(content=numero), AIMessage(content=pregunta)]
            salida.append(conversacion_ejecutor(turnos, intencion=tipo, origen_menu=tipo))
    return salida


def intake_nuevos() -> list[dict]:
    salida = []
    for saludo in SALUDOS:
        salida.append(conversacion_intake(saludo, intencion="saludo", confianza=0.95, continua=False))
    for pedido in PEDIDOS_HUMANO:
        salida.append(conversacion_intake(pedido, intencion="consulta", confianza=0.8, requiere_humano=True))
    # Con historial: aportar el dato pedido continúa el caso; un tema nuevo no.
    for frase, formal, categoria in RECLAMOS_INCOMPLETOS:
        historial = [
            {"actor": "ciudadano", "contenido": f"{frase.capitalize()} {random.choice(VAGOS)}"},
            {"actor": "agente_ia", "contenido": random.choice(PIDE_DIRECCION)},
        ]
        direccion = f"{random.choice(CALLES)} {random.randint(100, 5000)}"
        salida.append(conversacion_intake(
            direccion, intencion="reclamo", confianza=0.9,
            entidades={"categoria": categoria, "direccion": direccion}, historial=historial,
        ))
        turno = random.choice(TURNOS)
        salida.append(conversacion_intake(
            f"Otra cosa, necesito un turno de {turno}", intencion="reserva", confianza=0.9,
            continua=False, historial=historial,
        ))
    return salida


# --- Pautas generales (v3) ----------------------------------------------------

# (lo que cuenta el vecino, el reclamo formal, la categoría, el aviso que pide la
# pauta de emergencias). El aviso va primero, antes de pedir cualquier dato.
EMERGENCIAS = [
    ("hay un cable de luz caído en la vereda y saltan chispas", "Cable de luz caído con chispas en la vereda",
     "infraestructura", "Por favor, que nadie se acerque al cable. Si hay riesgo inmediato, llame al 911."),
    ("se está prendiendo fuego un contenedor de basura", "Contenedor de basura incendiándose",
     "servicio", "Si el fuego crece o hay personas cerca, llame ya a los bomberos al 100 y aléjese del contenedor."),
    ("hay olor a gas fuerte en la calle", "Olor a gas en la vía pública",
     "infraestructura", "No encienda nada ni se acerque. Si el olor es fuerte, llame al 911 desde un lugar seguro."),
    ("un árbol está por caerse sobre los autos", "Árbol con riesgo de caída sobre la calzada",
     "infraestructura", "Pida que nadie se quede debajo del árbol. Si hay riesgo inmediato, llame al 911."),
    ("se cayó una persona en un pozo de la vereda y está lastimada", "Pozo en la vereda donde se lastimó una persona",
     "infraestructura", "Si la persona está lastimada, llame primero a emergencias médicas al 107."),
    ("se inundó la esquina y hay un auto con gente adentro", "Esquina inundada con un auto atrapado",
     "infraestructura", "Si hay personas en peligro, llame ya al 911 o a los bomberos al 100."),
]
VIOLENCIA = [
    "Mi pareja me está amenazando y tengo miedo",
    "Mi vecina está sufriendo violencia de su marido, ¿qué hago?",
    "Me pegaron en mi casa y no sé a quién llamar",
]
TRATO = [
    ("¿Qué opinás del intendente?", "No puedo opinar sobre política ni sobre funcionarios. Sí lo puedo ayudar con un reclamo, un turno o una consulta sobre trámites: ¿qué necesita?"),
    ("¿A quién tengo que votar?", "No puedo opinar sobre política ni sobre elecciones. ¿Lo ayudo con algún trámite, reclamo o turno?"),
    ("Este gobierno es un desastre, ¿no te parece?", "Entiendo su malestar, pero no puedo opinar sobre política ni sobre la gestión. Si tiene un problema puntual, lo registro como reclamo: ¿qué pasó?"),
    ("¿Necesitás mi clave de Mi Argentina para el turno?", "No, nunca le voy a pedir contraseñas ni claves. Para el turno solo necesito el trámite, el día y la hora."),
    ("Te paso el número de mi tarjeta para pagar la multa", "Por favor, no me pase datos de su tarjeta: nunca se los voy a pedir por este medio. El pago de la multa se hace en los canales oficiales del organismo."),
    ("¿Me das la clave del wifi de la sede?", "No tengo esa información. Lo puedo ayudar con reclamos, turnos y consultas sobre trámites: ¿qué necesita?"),
]


def _con_direccion(frase: str) -> tuple[str, str]:
    direccion = f"{random.choice(CALLES)} {random.randint(100, 5000)}"
    return f"{frase.capitalize()} en {direccion}", direccion


def emergencias(n: int) -> list[dict]:
    """Con la pauta presente: primero el aviso de seguridad; después, si no está
    identificado, los datos; si lo está, el reclamo con el aviso adelante."""
    salida = []
    for _ in range(n):
        frase, formal, categoria, aviso = random.choice(EMERGENCIAS)
        mensaje, direccion = _con_direccion(frase)
        if random.random() < 0.5:
            turnos = [
                HumanMessage(content=mensaje),
                AIMessage(content=(
                    f"{aviso} Tomé nota de lo que pasa en {direccion}. Para registrar el reclamo a su "
                    "nombre necesito su nombre completo y su DNI."
                )),
            ]
            salida.append(conversacion_ejecutor(
                turnos, intencion="reclamo", identificado=False, canal=Canal.whatsapp, pautas=PAUTAS,
            ))
        else:
            reclamo = _llamada("crear_reclamo", {"descripcion": f"{formal} en {direccion}", "categoria": categoria})
            turnos = [HumanMessage(content=mensaje), AIMessage(content=aviso, tool_calls=[reclamo])]
            salida.append(conversacion_ejecutor(turnos, intencion="reclamo", pautas=PAUTAS))
    for mensaje in VIOLENCIA:
        turnos = [
            HumanMessage(content=mensaje),
            AIMessage(content=(
                "Si está en peligro ahora, llame al 911. Para orientación y ayuda en situaciones de "
                "violencia de género puede llamar al 144, las 24 horas y en forma gratuita. "
                "¿Quiere que lo atienda una persona del equipo?"
            )),
        ]
        salida.append(conversacion_ejecutor(turnos, intencion="consulta", canal=Canal.whatsapp, pautas=PAUTAS))
    return salida


def trato() -> list[dict]:
    salida = []
    for _ in range(3):
        for pregunta, respuesta in TRATO:
            turnos = [HumanMessage(content=pregunta), AIMessage(content=respuesta)]
            salida.append(conversacion_ejecutor(turnos, intencion="consulta", pautas=PAUTAS))
    return salida


def intake_emergencias() -> list[dict]:
    salida = []
    for frase, _, categoria, _ in EMERGENCIAS:
        mensaje, direccion = _con_direccion(frase)
        salida.append(conversacion_intake(
            mensaje, intencion="reclamo", confianza=0.9,
            entidades={"categoria": categoria, "direccion": direccion},
        ))
    return salida


# --- Cuarta versión: lo que falló con la v3 en conversaciones reales -----------

# Lo que agrega el vecino al reclamo, y cómo queda en la descripción. Con la v3,
# "y ayer se cayó una moto" terminó en una descripción con tres calles que nadie
# dijo: la descripción usa solo lo que contó.
DETALLES = [
    ("y ayer se cayó una moto", "se cayó una moto"),
    ("y ya hubo dos accidentes", "ya hubo dos accidentes"),
    ("desde hace una semana", "desde hace una semana"),
    ("y es peligroso para los chicos", "es peligroso para los chicos"),
    ("y nadie vino a verlo", "nadie vino a verlo"),
]
RESPUESTAS_CON_DNI = ["{n}, DNI {d}", "{n}, {d}", "Soy {n}, mi DNI es {d}", "{n} DNI {d}"]


def reclamos_tras_identificarse(n: int) -> list[dict]:
    """El turno después del pedido de datos, tal como lo ve el modelo hoy: el
    código ya registró la identidad (el prompt dice identificado) y el reclamo
    está en el historial. Una sola llamada, con lo que dijo el ciudadano; si no
    dio la dirección, se le pide en vez de inventarla."""
    salida = []
    for _ in range(n):
        canal = random.choice([Canal.whatsapp, Canal.whatsapp, Canal.email, Canal.voz])
        frase, formal, categoria = random.choice(RECLAMOS_INCOMPLETOS)
        nombre = random.choice(NOMBRES)
        dicho, _ = _dni()
        datos = HumanMessage(content=random.choice(RESPUESTAS_CON_DNI).format(n=nombre, d=dicho))
        pedido = AIMessage(content=pedido_de_identificacion("crear_reclamo", canal))
        if random.random() < 0.3:
            turnos = [
                HumanMessage(content=f"{frase.capitalize()} {random.choice(VAGOS)}"),
                pedido,
                datos,
                AIMessage(content=random.choice(PIDE_DIRECCION)),
            ]
        else:
            direccion = f"{random.choice(CALLES)} {random.randint(100, 5000)}"
            detalle, detalle_formal = random.choice(DETALLES) if random.random() < 0.6 else ("", "")
            contado = f"{frase.capitalize()} en {direccion} {detalle}".strip()
            descripcion = f"{formal} en {direccion}" + (f", {detalle_formal}" if detalle_formal else "")
            reclamo = _llamada("crear_reclamo", {"descripcion": descripcion, "categoria": categoria})
            turnos = [
                HumanMessage(content=random.choice([contado, f"Hola, {frase} en {direccion} {detalle}".strip()])),
                pedido,
                datos,
                AIMessage(content="", tool_calls=[reclamo]),
            ]
        salida.append(conversacion_ejecutor(turnos, intencion="reclamo", canal=canal))
    return salida


PREGUNTAS_POR_SU_CASO = [
    "¿Cómo va el reclamo del pozo?", "Hola, les escribo por correo. ¿Cómo va mi reclamo?",
    "¿Qué pasó con el reclamo de la luz que hice?", "¿En qué quedó mi trámite?",
    "¿Hay novedades de mi reclamo?", "¿Cómo sigue lo del árbol caído?",
    "Quería saber el estado de mi reclamo", "¿Me confirman si sigue en pie mi turno?",
    "Hice un reclamo por WhatsApp, ¿cómo va?", "¿Tienen novedades de lo que reclamé la semana pasada?",
]


def consultas_sin_identificar(n: int) -> list[dict]:
    """Un contacto que todavía no está a nombre de nadie pregunta por su caso:
    casi siempre lo inició por otro canal. Se le piden los datos para buscarlo
    (el mismo texto que arma el código), no "no encontré casos"."""
    salida = []
    for _ in range(n):
        canal = random.choice([Canal.whatsapp, Canal.email, Canal.email, Canal.voz])
        turnos = [
            HumanMessage(content=random.choice(PREGUNTAS_POR_SU_CASO)),
            AIMessage(content=pedido_de_identificacion_para_consulta(canal)),
        ]
        # El intake a veces la clasifica reclamo por la palabra: las dos.
        intencion = random.choice(["consulta", "consulta", "reclamo"])
        salida.append(conversacion_ejecutor(turnos, intencion=intencion, canal=canal, identificado=False))
    return salida


def _documento(titulo: str) -> str:
    """Un documento de la base tal como lo arma `buscar_documentos_relevantes`."""
    contenido = dict(DOCUMENTOS)[titulo]
    return f"{titulo}: {contenido}"


# (tipo, de qué trata, documento que lo responde, preguntas de seguimiento,
# respuesta a partir de ese documento). Los plazos salen de los documentos de
# `scripts/documentos_de_ejemplo.py`, que son los que carga la demo.
SEGUIMIENTOS = [
    ("reclamo", "pozo en la calzada en {d}", "Baches, pozos y hundimientos en la calzada",
     ["¿Y para cuándo lo arreglan?", "¿Cuánto tardan en arreglarlo?", "¿Y en cuántos días lo tapan?"],
     "El bacheo común se hace dentro de los 10 días hábiles. Si el pozo impide el paso de "
     "peatones o deja hierros expuestos, se atiende como urgente."),
    ("reclamo", "luminaria apagada en {d}", "Alumbrado público: luminarias apagadas o dañadas",
     ["¿Cuándo vienen a arreglar la luz?", "¿Y cuánto tarda eso?"],
     "El plazo de reparación del alumbrado es de 5 días hábiles. Si hay riesgo eléctrico, "
     "como un cable caído, se atiende dentro de las 24 horas."),
    ("reclamo", "desagüe tapado en {d}", "Pérdidas de agua, cloacas y desagües tapados",
     ["¿Cuándo lo destapan?", "¿Y para cuándo calculan que vienen?"],
     "Los sumideros tapados se limpian dentro de las 72 horas. Si el agua inunda la calzada "
     "o compromete una vivienda, se atiende como urgencia."),
    ("reclamo", "ramas que tapan la luminaria en {d}", "Poda de árboles y ramas caídas",
     ["¿Cuándo vienen a podar?", "¿Y para cuándo la poda?"],
     "La poda programada se hace entre mayo y agosto. Si el árbol está caído o con riesgo "
     "de caerse, se atiende como urgencia dentro de las 24 horas."),
    ("reclamo", "no pasa el camión de la basura en {d}", "Recolección de residuos, basura y contenedores",
     ["¿A qué hora pasa el camión?", "¿Y qué días pasa?"],
     "La recolección domiciliaria pasa de lunes a sábado entre las 20 y las 23, y los "
     "reciclables se retiran martes y viernes."),
    ("reserva", "turno de licencia de conducir", "Licencia de conducir por primera vez",
     ["¿Y qué tengo que llevar?", "¿Qué papeles necesito para ese turno?"],
     "Para la licencia por primera vez necesita DNI vigente, certificado de grupo sanguíneo, "
     "libre deuda de infracciones y el curso teórico aprobado."),
    ("tramite", "habilitación de un local comercial", "Habilitación de comercios minoristas",
     ["¿Cuánto tarda la habilitación?", "¿Y en cuánto sale?"],
     "La habilitación simplificada resuelve en 15 días hábiles los locales de menos de 200 "
     "metros cuadrados."),
]


PALABRA_DEL_TIPO = {"reclamo": "reclamo", "reserva": "turno", "tramite": "trámite"}


def _pregunta_por(tipo: str) -> str:
    """La pregunta por el estado nombrando el mismo tipo de caso que se contesta."""
    return random.choice([
        "¿Cómo va mi {t}?", "¿Hay novedades de mi {t}?", "Quería saber el estado de mi {t}",
        "Hola, ¿en qué quedó mi {t}?",
    ]).format(t=PALABRA_DEL_TIPO[tipo])


def seguimientos(n: int) -> list[dict]:
    """Ya identificado y con el estado de su caso en el historial, pregunta algo
    más. Con la v3, el modelo le volvía a pedir nombre y DNI. Se contesta con la
    información del organismo; si no está, se le dice (el mismo texto que usa
    el código cuando el modelo insiste)."""
    salida = []
    for _ in range(n):
        tipo, de_que, titulo, preguntas, respuesta = random.choice(SEGUIMIENTOS)
        de_que = de_que.format(d=f"{random.choice(CALLES)} {random.randint(100, 5000)}")
        caso = _caso(tipo, de_que, random.choice(["abierto", "en_progreso"]))
        estado = (
            f"Su {tipo} por {de_que} {ESTADO_EN_PALABRAS[caso['estado']]}.\n\n"
            f"Número de caso: {caso['referencia']}"
        )
        otro = random.choice([t for t, _ in DOCUMENTOS if t != titulo])
        if random.random() < 0.2:
            conocimiento, final = [_documento(otro)], NO_TENGO_ESE_DATO
        else:
            conocimiento = [_documento(titulo)] + ([_documento(otro)] if random.random() < 0.5 else [])
            random.shuffle(conocimiento)
            final = respuesta
        turnos = [
            HumanMessage(content=_pregunta_por(tipo)),
            AIMessage(content=estado),
            HumanMessage(content=random.choice(preguntas)),
            AIMessage(content=final),
        ]
        salida.append(conversacion_ejecutor(
            turnos, intencion="consulta", canal=random.choice([Canal.whatsapp, Canal.email]),
            conocimiento=conocimiento,
        ))
    return salida


def intake_consultas_de_estado() -> list[dict]:
    """Preguntar por un reclamo es una consulta, aunque diga "reclamo": con la
    v3, "¿cómo va el reclamo del pozo?" salía reclamo."""
    salida = []
    for pregunta in PREGUNTAS_POR_SU_CASO:
        for _ in range(2):
            salida.append(conversacion_intake(pregunta, intencion="consulta", confianza=0.9))
    for tipo, de_que, _, preguntas, _ in SEGUIMIENTOS:
        de_que = de_que.format(d=f"{random.choice(CALLES)} {random.randint(100, 5000)}")
        historial = [
            {"actor": "ciudadano", "contenido": _pregunta_por(tipo)},
            {"actor": "agente_ia", "contenido": f"Su {tipo} por {de_que} {ESTADO_EN_PALABRAS['abierto']}."},
        ]
        for pregunta in preguntas:
            salida.append(conversacion_intake(pregunta, intencion="consulta", confianza=0.9, historial=historial))
    return salida


# Las emergencias que la v3 contestó sin aviso. El aviso es el mismo que
# antepone el código (`app/agents/seguridad.py`), para que lo que aprende el
# modelo y la red de seguridad digan lo mismo.
GAS = [
    ("hay mucho olor a gas en la esquina", "Olor a gas en la vía pública"),
    ("sale olor a gas de una cámara de la vereda", "Olor a gas en una cámara de la vereda"),
    ("huele a gas en toda la cuadra", "Olor a gas en la cuadra"),
    ("hay una pérdida de gas en la calle", "Pérdida de gas en la vía pública"),
]
VIOLENCIA_V4 = [
    "Mi ex me amenaza por mensajes todos los días",
    "Mi marido me pega y no sé qué hacer",
    "Escucho que en el departamento de al lado le pegan a una mujer",
    "Tengo miedo, mi pareja me está amenazando",
    "Me están amenazando y no sé a dónde recurrir",
    "Mi hermana sufre violencia de su novio, ¿cómo la ayudo?",
]


def emergencias_v4(n_gas: int) -> list[dict]:
    salida = []
    for _ in range(n_gas):
        frase, formal = random.choice(GAS)
        mensaje, direccion = _con_direccion(frase)
        aviso, _ = aviso_de_seguridad(mensaje)
        if random.random() < 0.5:
            turnos = [
                HumanMessage(content=mensaje),
                AIMessage(content=(
                    f"{aviso} Tomé nota de lo que pasa en {direccion}. Para registrar el reclamo a su "
                    "nombre necesito su nombre completo y su DNI."
                )),
            ]
            salida.append(conversacion_ejecutor(
                turnos, intencion="reclamo", identificado=False, canal=Canal.whatsapp, pautas=PAUTAS,
            ))
        else:
            reclamo = _llamada(
                "crear_reclamo", {"descripcion": f"{formal} en {direccion}", "categoria": "infraestructura"}
            )
            turnos = [HumanMessage(content=mensaje), AIMessage(content=aviso, tool_calls=[reclamo])]
            salida.append(conversacion_ejecutor(turnos, intencion="reclamo", pautas=PAUTAS))
    for mensaje in VIOLENCIA_V4:
        aviso, _ = aviso_de_seguridad(mensaje)
        for canal in (Canal.whatsapp, Canal.email):
            turnos = [
                HumanMessage(content=mensaje),
                AIMessage(content=f"{aviso} ¿Quiere que lo atienda una persona del equipo?"),
            ]
            salida.append(conversacion_ejecutor(turnos, intencion="consulta", canal=canal, pautas=PAUTAS))
    return salida


# --- Armado ------------------------------------------------------------------


def _leer(nombre: str) -> list[dict]:
    return [json.loads(linea) for linea in open(DATA / nombre, encoding="utf-8") if linea.strip()]


def _submuestrear_externos(ejemplos: list[dict], limite: int) -> list[dict]:
    """Toma `limite` ejemplos de MASSIVE/MULTI3NLU++ repartidos por intención."""
    por_intencion = defaultdict(list)
    for e in ejemplos:
        por_intencion[e["intencion"]].append(e)
    cuota = limite // len(por_intencion)
    elegidos = []
    for grupo in por_intencion.values():
        random.shuffle(grupo)
        elegidos += grupo[:cuota]
    return elegidos


def _armar(origen: list[dict], limite_externos: int) -> list[dict]:
    externos = [e for e in origen if e["fuente"] in ("massive", "multi3nlu")]
    propios = [e for e in origen if e["fuente"] in ("manual", "manual_generado")]
    salida = [intake_desde_ejemplo(e) for e in _submuestrear_externos(externos, limite_externos)]
    salida += [intake_desde_ejemplo(e) for e in propios]
    salida += [c for e in propios if (c := ejecutor_desde_ejemplo(e))]
    return salida


def _nuevos() -> list[dict]:
    return (
        reclamos_en_dos_turnos(70)
        + reservas(60, 50)
        + consultas_de_estado(70)
        + identificaciones(60)
        + pedidos_de_humano()
        + elecciones_de_menu()
        + intake_nuevos()
        + emergencias(60)
        + trato()
        + intake_emergencias()
        + reclamos_tras_identificarse(60)
        + consultas_sin_identificar(40)
        + seguimientos(60)
        + intake_consultas_de_estado()
        + emergencias_v4(30)
    )


def _prueba() -> list[dict]:
    """El conjunto de prueba de tool calling, con el prompt del ejecutor y las
    herramientas de la intención esperada. Solo hasta el mensaje del ciudadano:
    lo que sigue lo genera el modelo en la celda de evaluación."""
    salida = []
    for e in _leer("prueba_tool_calling.jsonl"):
        conversacion = conversacion_ejecutor(
            [HumanMessage(content=e["instruccion"])], intencion=e["intencion"], canal=Canal.whatsapp, pautas=None
        )
        conversacion["esperado"] = e["llamada_herramienta"]
        conversacion["instruccion"] = e["instruccion"]
        salida.append(conversacion)
    return salida


def _escribir(nombre: str, filas: list[dict]) -> None:
    with open(DATA / nombre, "w", encoding="utf-8") as archivo:
        for fila in filas:
            archivo.write(json.dumps(fila, ensure_ascii=False) + "\n")


def main() -> None:
    nuevos = _nuevos()
    random.shuffle(nuevos)
    corte = int(len(nuevos) * PROPORCION_VALIDACION)
    limite_val = int(MAX_INTAKE_EXTERNOS * PROPORCION_VALIDACION)

    train = _armar(_leer("train.jsonl"), MAX_INTAKE_EXTERNOS) + nuevos[corte:]
    validacion = _armar(_leer("validacion.jsonl"), limite_val) + nuevos[:corte]
    random.shuffle(train)
    random.shuffle(validacion)

    _escribir("app_train.jsonl", train)
    _escribir("app_validacion.jsonl", validacion)
    _escribir("app_prueba.jsonl", _prueba())

    for nombre, filas in [("train", train), ("validacion", validacion)]:
        print(f"{nombre}: {len(filas)} conversaciones {dict(Counter(f['tipo'] for f in filas))}")
    print(f"prueba: {len(_leer('prueba_tool_calling.jsonl'))} ejemplos de tool calling")


if __name__ == "__main__":
    main()
