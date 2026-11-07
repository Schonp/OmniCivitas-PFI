import json
import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.agents.cancelacion import atender_turno
from app.agents.fechas import fecha_hora_dicha
from app.agents.confirmacion import (
    agradecimiento,
    confirmacion,
    dia_en_palabras,
    estado_de_casos,
    MARCA_PEDIDO_PARA_CONSULTA,
    horario_no_disponible,
    pedido_de_dia_y_hora,
    pedido_de_identificacion,
    pedido_de_identificacion_para_consulta,
)
from app.agents.state import AgentState
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.agents.contexto import obtener_ciudadano_por_canal
from app.agents.eleccion import ETIQUETA_TIPO
from app.agents.identidad import DNI, extraer_identidad, sin_nombre_inventado
from app.agents.seguridad import ofrece_dato_sensible, respuesta_dato_sensible
from app.db.crud import ciudadanos
from app.db.crud.turnos import (
    ReservaNoDisponible,
    ahora_local,
    listar_agendas,
    proximos_horarios_libres,
)
from app.db.models import Turno
from app.tools import consultas, reclamos, reservas
from app.tools.reclamos import CategoriaReclamo

logger = logging.getLogger(__name__)

MAX_ITERACIONES = 3
# Las herramientas que crean algo a nombre del ciudadano: no corren mientras
# no haya informado su DNI (ver `nodo_ejecutor`).
GESTIONES = {"crear_reclamo", "crear_reserva"}
ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
MAX_FALLOS = 1

SYSTEM_EJECUTOR = """Sos el agente de atención ciudadana de un organismo público \
argentino. Resolvés la solicitud del ciudadano de dos maneras: respondés las consultas con la
información del organismo, y ejecutás las gestiones con las herramientas disponibles.

Reglas:
- Tratá al ciudadano de "usted", con lenguaje simple y claro, sin tecnicismos.
- Si la sección "Información del organismo" responde lo que pregunta el ciudadano,
  contestale con esa información y no llames a ninguna herramienta: informar
  requisitos, plazos y horarios es resolver la consulta.
- Usá las herramientas para ejecutar acciones; no inventes números de caso ni estados.
- Si el ciudadano ya dio los datos que pide la herramienta, llamala en ese mismo turno,
  sin pedirle confirmación.
- Si falta un dato necesario, no llames a la herramienta: preguntá justo lo que falta,
  en una sola pregunta.
- Nunca inventes un parámetro que el ciudadano no haya dicho.
- Al informarle un número de caso al ciudadano usá siempre el campo `referencia`\n  que devuelve la herramienta (ej. REC-5072BFA2). Nunca le muestres `caso_id`.
- Saludá al inicio de la conversación y, si sabés el nombre del ciudadano, usalo.
- Al terminar, confirmá qué se hizo y cuál es el próximo paso.
- Derivá solo si no podés resolver ni con la información del organismo ni con las\n  herramientas. Nunca derives una consulta que ya podés contestar. Cuando\n  corresponda derivar, no te limites a decir que no podés: llamá a\n  `derivar_a_operador` para que una persona la retome."""

FORMATO_TEXTO = """

Formato de la respuesta (el mensaje se lee en WhatsApp o en un correo):
- Escribí en texto plano. Nada de Markdown: ni asteriscos, ni almohadillas, ni guiones
  de lista. El ciudadano ve esos símbolos tal cual, no se convierten en negrita.
- Separá las ideas en párrafos cortos con una línea en blanco entre medio, en vez de
  un bloque largo.
- Cuando informes datos concretos (número de caso, área, plazo, día y hora de un
  turno), poné cada uno en su propia línea con una etiqueta adelante.
- No más de cuatro o cinco líneas de texto corrido por bloque."""

# Un párrafo con "etiqueta: valor" por línea se lee perfecto y se escucha
# rarísimo (el TTS lo sintetiza como una lista entrecortada, con pausas donde
# no las hay en una conversación real). Y cada palabra de más en una llamada
# es audio real que hay que sintetizar y esperar -- ver voz_asr_tts/DEVLOG.md,
# "Diferenciar voz de texto".
FORMATO_VOZ = """

Formato de la respuesta (es una llamada telefónica: se escucha, no se lee):
- Hablá en oraciones completas y fluidas, como en una conversación real. Nunca uses
  listas, numeración ni "etiqueta: valor" en líneas separadas.
- Sé breve: dos o tres oraciones cortas por turno, nunca un discurso largo.
- Si tenés que decir un número de caso, decilo una sola vez y seguí; no lo repitas
  ni lo deletrees letra por letra.
- No ofrezcas un menú de opciones: preguntá una sola cosa concreta por vez."""

# Se agrega al system prompt cuando el ciudadano escribe por primera vez y todavía
# no sabemos quién es. El organismo necesita identificarlo para gestionar cualquier
# trámite a su nombre, así que ese es el primer paso de la conversación.
INSTRUCCION_IDENTIFICACION = """

IMPORTANTE — es el primer contacto y todavía no sabés quién es:
- Arrancá saludando y presentándote como la atención ciudadana del organismo, en una
  línea. Que se note que del otro lado hay un servicio, no un formulario.
- Decile que tomaste nota de lo que necesita, en tus palabras, para que vea que lo
  entendiste antes de pedirle nada.
- Recién ahí pedile su nombre completo y su DNI, explicando en pocas palabras que
  el organismo los necesita para gestionar la solicitud a su nombre.
- Si en este mensaje ya los informó, registralos con `registrar_identidad` y seguí
  con la gestión en la misma respuesta, sin volver a pedirlos.
- Hasta tener esos datos no uses ninguna otra herramienta, salvo `derivar_a_operador`
  si pide hablar con una persona."""


def construir_tools(db: AsyncSession, state: AgentState) -> list[BaseTool]:
    """Cierra db/ciudadano/canal para que el LLM solo vea los parámetros de negocio."""
    ciudadano_id = uuid.UUID(state["ciudadano_id"])
    canal = Canal(state["canal"])
    # El caso que ya trae la conversación, si `_abrir_caso` lo abrió en un
    # mensaje anterior por faltar un dato para poder ejecutar. Las tools que
    # crean casos lo usan para completar ese caso en vez de abrir otro cuando
    # por fin llega el dato que faltaba.
    caso_id = uuid.UUID(state["caso_id"]) if state.get("caso_id") else None

    @tool
    async def registrar_identidad(nombre_completo: str, documento: str) -> dict:
        """Registra el nombre y el DNI que informó el ciudadano. Usar en cuanto los
        proporcione, antes de gestionar su solicitud. `documento` es solo el número,
        sin puntos ni espacios."""
        ciudadano = await ciudadanos.identificar_ciudadano(
            db, ciudadano_id, documento=documento.strip(), nombre=nombre_completo.strip()
        )
        return {"identificado": True, "nombre": ciudadano.nombre, "documento": ciudadano.documento}

    @tool
    async def derivar_a_operador(motivo: str) -> dict:
        """Deriva la solicitud a un operador humano. Usar cuando el ciudadano pide
        algo que ninguna otra herramienta puede resolver, en vez de limitarse a
        decirle que no se puede. `motivo` describe en una frase qué necesita."""
        return {"derivado": True, "motivo": motivo}

    @tool
    async def crear_reclamo(descripcion: str, categoria: CategoriaReclamo) -> dict:
        """Crea un nuevo reclamo para el ciudadano. Usar cuando el ciudadano avisa de
        un problema que el organismo tiene que atender.

        `categoria`:
        - "infraestructura": un daño en la vía pública. Árbol caído o seco, poste o
          foco de luz quemado, pozo o bache, vereda rota, cable caído, semáforo que
          no anda, caño roto, desagüe tapado, tapa de alcantarilla rota.
        - "servicio": un servicio municipal que no se presta o se presta mal.
          Recolección de basura, barrido, poda, desratización, ruidos molestos,
          limpieza, mantenimiento de instalaciones municipales (caniles, playones
          deportivos, mercados).
        - "tramite": un problema administrativo. Pagos o tasas no reconocidos,
          cobros duplicados, deudas o multas que no corresponden, trámites o
          expedientes sin respuesta. No necesita dirección: registralo con lo que
          contó el ciudadano.

        Para "infraestructura" y "servicio" hace falta saber dónde es: una calle con
        altura, una esquina o un lugar identificable (ej. "la plaza San Martín").
        "Cerca de mi casa" o "en mi cuadra" no alcanzan: preguntá la dirección."""
        return await reclamos.crear_reclamo(
            db,
            ciudadano_id=ciudadano_id,
            canal=canal,
            descripcion=descripcion,
            categoria=categoria,
            caso_id=caso_id,
        )

    @tool
    async def crear_reserva(turno: str, fecha_hora: str) -> dict:
        """Reserva un turno para el ciudadano en una de las agendas del organismo.
        Usar cuando el ciudadano pide un turno o cita (ej. renovación de licencia,
        atención presencial). `turno` es el nombre de la agenda (la lista de turnos
        disponibles viene en la información del organismo) y `fecha_hora` va en
        formato AAAA-MM-DD HH:MM. Si el ciudadano no dijo día y horario, preguntáselo
        antes de reservar."""
        return await reservas.crear_reserva(
            db,
            ciudadano_id=ciudadano_id,
            canal=canal,
            turno=turno,
            fecha_hora=fecha_hora,
            caso_id=caso_id,
        )

    @tool
    async def consultar_estado_caso(referencia: str = "") -> dict:
        """Consulta el estado de un caso del ciudadano. Usar cuando pregunta cómo
        va un reclamo, reserva o trámite.

        Si el ciudadano identificó de cuál se trata —el número de caso o unas
        palabras de qué era (ej. "el árbol caído", "la renovación del DNI")—,
        pasalo en `referencia`. Si no dijo cuál ("¿cómo viene mi trámite?"),
        llamala igual con `referencia` vacía: no le preguntes antes. Si tiene más de un caso y no queda claro a cuál
        se refiere, la herramienta devuelve `varios_posibles=true` con la lista:
        no elijas uno vos, preguntale al ciudadano cuál es antes de responder."""
        return await consultas.consultar_estado_caso(
            db, ciudadano_id=ciudadano_id, referencia=referencia or None
        )

    tools_por_intencion = {
        "reclamo": [crear_reclamo, consultar_estado_caso],
        "reserva": [crear_reserva, consultar_estado_caso],
        "consulta": [consultar_estado_caso],
    }
    tools = tools_por_intencion.get(state["intencion"] or "", [consultar_estado_caso])
    # Sin identificar, el ejecutor tiene que poder registrar el nombre y el DNI
    # en cuanto el ciudadano los informe, cualquiera sea la intención detectada.
    # Y tiene que poder completar la gestión que el ciudadano contó antes de
    # identificarse: el mensaje que trae los datos ("Laura Pérez, 30.111.291")
    # no dice si era un reclamo o un turno, eso está en el historial.
    if not state.get("identificado"):
        tools = [registrar_identidad, crear_reclamo, crear_reserva, consultar_estado_caso]
    elif state.get("recien_identificado"):
        # Se identificó en este mismo mensaje: la gestión pendiente sigue siendo
        # la del historial, no la que sugiere el mensaje con sus datos.
        tools = [crear_reclamo, crear_reserva, consultar_estado_caso]
    # Siempre disponible: el ciudadano tiene que poder llegar a una persona,
    # que fue lo más pedido después de la reserva de turnos en la encuesta.
    return [*tools, derivar_a_operador]


def _sin_markdown(texto: str) -> str:
    """Quita el Markdown que el modelo escribe por costumbre.

    WhatsApp usa un solo asterisco para la negrita y el correo va en texto plano:
    en los dos casos un `**` llega literal a la pantalla del ciudadano. El prompt
    ya lo pide, pero el modelo se desvía y esto es la red de seguridad.
    """
    limpio = re.sub(r"\*\*(.+?)\*\*", r"\1", texto, flags=re.S)
    limpio = re.sub(r"__(.+?)__", r"\1", limpio, flags=re.S)
    limpio = re.sub(r"^#{1,6}\s+", "", limpio, flags=re.M)
    return limpio


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _sin_identificadores_internos(texto: str) -> str:
    """Quita las líneas con un identificador interno (el `caso_id`).

    El prompt pide usar siempre la referencia (REC-...) y nunca el id, pero el
    modelo a veces copia el `caso_id` que vuelve en el resultado de la
    herramienta: en una prueba respondió "Número de caso: 1807db61-d26c-...".
    Para el ciudadano es ruido, y es un dato interno del sistema.
    """
    lineas = [linea for linea in texto.splitlines() if not _UUID.search(linea)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


_REFERENCIA = re.compile(r"\b(?:REC|RES|CON|TRA)-[0-9A-F]{8}\b", re.IGNORECASE)


def sin_referencias_ajenas(texto: str, permitidas: set[str]) -> str:
    """Quita las líneas con un número de caso que no es de este ciudadano.

    En una prueba sobre el sistema completo, el modelo contestó una consulta
    con "Número de caso: REC-20194FB3" cuando el caso real era REC-20194FB2: un
    número que no existe, o que es de otra persona, no puede llegarle al
    ciudadano. Las confirmaciones armadas por código siempre pasan.
    """
    permitidas = {referencia.upper() for referencia in permitidas}
    lineas = [
        linea
        for linea in texto.splitlines()
        if all(r.upper() in permitidas for r in _REFERENCIA.findall(linea))
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


async def _referencias_del_ciudadano(db: AsyncSession, ciudadano_id: str | None) -> set[str]:
    if not ciudadano_id:
        return set()
    casos = await db.execute(select(Caso).where(Caso.ciudadano_id == uuid.UUID(ciudadano_id)))
    return {caso.referencia for caso in casos.scalars().all()}


def _texto(mensaje: AIMessage) -> str:
    if isinstance(mensaje.content, str):
        return _sin_identificadores_internos(_sin_markdown(mensaje.content))
    partes = [
        bloque.get("text", "")
        for bloque in mensaje.content
        if isinstance(bloque, dict) and bloque.get("type") == "text"
    ]
    return _sin_identificadores_internos(_sin_markdown("".join(partes)))


def prompt_del_sistema(
    canal: Canal,
    *,
    conocimiento: list[str] | None = None,
    pautas: list[str] | None = None,
    origen_menu: str | None = None,
    identificado: bool = True,
    hoy: datetime | None = None,
) -> str:
    """El prompt del sistema del ejecutor, tal como lo ve el modelo.

    Es la única fuente: lo usan el nodo, la medición del modelo local
    (`scripts/evaluar_modelo_local.py`) y el armado del dataset de
    fine-tuning (`finetuning/armar_dataset_app.py`), para que el modelo se
    entrene y se mida con exactamente el texto que recibe en producción.
    """
    hoy = hoy or datetime.now(ZONA_HORARIA)
    # Sin la fecha, "el jueves a las 10" no tiene cómo pasar a AAAA-MM-DD.
    partes = [SYSTEM_EJECUTOR, f"\n\nHoy es {dia_en_palabras(hoy)} de {hoy.year}."]
    partes.append(FORMATO_VOZ if canal == Canal.voz else FORMATO_TEXTO)
    if pautas:
        # Antes del pedido de identificación: una pauta como "en una emergencia,
        # primero el número de emergencias" tiene que poder ir antes de pedir
        # datos. Los controles que importan (sin DNI no hay gestión, nada de
        # datos inventados) los aplica el código, así que una pauta no los saltea.
        partes.append("\n\nPautas del organismo (valen para toda la conversación):\n" + "\n".join(pautas))
    if not identificado:
        # Mientras arrastre el documento provisorio del alta automática, el
        # organismo no sabe a nombre de quién gestionar: primero nombre y DNI.
        partes.append(INSTRUCCION_IDENTIFICACION)
    if conocimiento:
        partes.append(
            "\n\nInformación del organismo (fuente oficial: usala para responder "
            "consultas sobre requisitos, plazos y horarios):\n" + "\n".join(conocimiento)
        )
    if origen_menu:
        # El mensaje que sigue es el número que tocó en el menú de inicio, no
        # una descripción: sin este aviso, el modelo ve un "1" o un "2" sueltos
        # y o los ignora (vuelve a saludar) o le pregunta al ciudadano qué quiso
        # decir con el número.
        etiqueta = ETIQUETA_TIPO.get(origen_menu, origen_menu)
        partes.append(
            f'\n\nEl ciudadano acaba de elegir "{etiqueta}" en el menú de inicio '
            "(el mensaje que sigue es solo el número de esa opción, no una "
            "descripción). Todavía no contó de qué se trata: arrancá preguntándole "
            "eso, en una frase, sin repetirle el saludo ni el menú."
        )
    return "".join(partes)


# Palabras que el modelo agrega al normalizar una dirección sin que el
# ciudadano las haya escrito así ("Avenida" pasa a "Av."): no son datos nuevos.
_ABREVIATURAS = {"av", "avda", "avenida", "calle", "esquina", "altura", "barrio", "plaza"}


def datos_inventados(descripcion: str, dichos_del_ciudadano: list[str]) -> list[str]:
    """Números y nombres propios de la descripción que el ciudadano no dijo.

    El modelo a veces completa la dirección de un reclamo que el ciudadano no
    dio: en una prueba sobre el sistema completo registró un pozo "en la esquina
    de Lavalle y Córdoba" cuando el ciudadano solo había preguntado por el
    estado de su reclamo. Las cifras y los nombres propios de una dirección son
    justo lo que no puede inventar, y se pueden verificar contra lo que el
    ciudadano escribió.
    """
    dicho = " ".join(dichos_del_ciudadano).lower()
    palabras_dichas = set(re.findall(r"[a-záéíóúñü0-9]+", dicho))
    faltantes = []
    for indice, palabra in enumerate(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñü0-9]+", descripcion)):
        es_numero = palabra.isdigit()
        es_nombre_propio = palabra[:1].isupper() and indice > 0
        if not (es_numero or es_nombre_propio):
            continue
        if palabra.lower() in _ABREVIATURAS or palabra.lower() in palabras_dichas:
            continue
        faltantes.append(palabra)
    return faltantes


_SALUDO_INICIAL = re.compile(
    r"^\s*(?:hola|buen(?:os|as)?(?:\s+(?:d[ií]as?|tardes|noches))?)\b[\s,.!¡]*", re.IGNORECASE
)
_MIN_PALABRAS_EN_COMUN = 2


def descripcion_del_ciudadano(descripcion: str, dichos_del_ciudadano: list[str]) -> str | None:
    """El mensaje del ciudadano que cuenta lo mismo que la descripción del
    modelo, para registrar el reclamo con sus palabras; None si ninguno alcanza.

    Se descarta el mensaje con el DNI (es la respuesta al pedido de datos) y
    se exige que comparta al menos dos palabras con lo que propuso el modelo.
    """
    clave = {p for p in re.findall(r"\w+", descripcion.lower()) if len(p) >= 4 or p.isdigit()}
    mejor, en_comun = None, 0
    for dicho in dichos_del_ciudadano:
        if DNI.search(dicho):
            continue
        cantidad = len(clave & set(re.findall(r"\w+", dicho.lower())))
        if cantidad > en_comun:
            mejor, en_comun = dicho, cantidad
    if mejor is None or en_comun < _MIN_PALABRAS_EN_COMUN:
        return None
    texto = _SALUDO_INICIAL.sub("", mejor).strip()
    return texto[:1].upper() + texto[1:] if texto else None


# Palabras de los nombres de agenda que no distinguen una de otra.
_GENERICAS_DE_AGENDA = {
    "de", "del", "la", "el", "en", "y", "para", "turno", "turnos", "centro",
    "atencion", "renovacion",
}
_MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
_DIA_DICHO = re.compile(
    r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|hoy|manana|pasado)\b"
    r"|\b\d{1,2}\s*/\s*\d{1,2}\b"
    rf"|\b\d{{1,2}}\s+de\s+({_MESES})\b"
)


def _normalizado(texto: str) -> str:
    return texto.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))


def agenda_nombrada(agendas: list[Turno], dichos_del_ciudadano: list[str]) -> Turno | None:
    """La agenda que nombró el ciudadano ("licencia", "DNI", "CeSAC"), si nombró
    exactamente una.

    En una prueba con el modelo real, el ciudadano pidió turno para la licencia
    y el modelo reservó en el centro de salud: el nombre de la agenda lo copia
    de una lista, y se equivoca de renglón. Lo que el ciudadano dijo manda.
    """
    dicho = set(re.findall(r"\w+", _normalizado(" ".join(dichos_del_ciudadano))))
    nombradas = [
        agenda
        for agenda in agendas
        if dicho
        & {
            palabra
            for palabra in re.findall(r"\w+", _normalizado(agenda.nombre))
            if len(palabra) >= 3 and palabra not in _GENERICAS_DE_AGENDA
        }
    ]
    return nombradas[0] if len(nombradas) == 1 else None


_HABLA_DE_TURNO = re.compile(r"\bturnos?\b|\breserv\w*|\bcitas?\b", re.IGNORECASE)


async def _es_pedido_de_turno(state: AgentState, db: AsyncSession, dichos: list[str]) -> bool:
    """La conversación es por un turno: la intención es reservar y el ciudadano
    habló de un turno o nombró una agenda. Con las dos cosas, un reclamo es un
    error del modelo y no un reclamo que el intake clasificó mal."""
    if state.get("intencion") != "reserva":
        return False
    if any(_HABLA_DE_TURNO.search(dicho) for dicho in dichos):
        return True
    return agenda_nombrada(await listar_agendas(db), dichos) is not None


def dijo_un_dia(dichos_del_ciudadano: list[str]) -> bool:
    """Si el ciudadano nombró un día ("el jueves", "mañana", "5/11", "5 de
    noviembre"). Sin eso, la fecha de la reserva la inventó el modelo."""
    return bool(_DIA_DICHO.search(_normalizado(" ".join(dichos_del_ciudadano))))


# Lo que el modelo afirma haber hecho, para comparar con lo que hizo.
_CONFIRMA_RESERVA = re.compile(r"\breservé\b|\bqued[oó] reservad[oa]\b", re.IGNORECASE)
_CONFIRMA_RECLAMO = re.compile(
    r"\bregistré (su|el) reclamo\b|\breclamo qued[oó] registrado\b", re.IGNORECASE
)
NO_QUEDO_RESERVADO = "Todavía no quedó reservado. ¿Me confirma el trámite, el día y la hora?"
NO_QUEDO_REGISTRADO = "Todavía no registré su reclamo. ¿Me cuenta qué pasó y en qué dirección?"


def ultima_fecha_hora_dicha(mensajes_del_ciudadano: list[str]) -> str | None:
    """El día y la hora del mensaje más reciente que los trae, en el formato
    de la herramienta. `mensajes_del_ciudadano` va del más nuevo al más viejo."""
    ahora = ahora_local()
    for mensaje in mensajes_del_ciudadano:
        momento = fecha_hora_dicha(mensaje, ahora)
        if momento is not None:
            return momento.strftime(reservas.FORMATO_FECHA_HORA)
    return None


async def _sin_confirmaciones_inventadas(
    respuesta: AIMessage, db: AsyncSession, resultado_ejecucion: dict, dichos: list[str]
) -> AIMessage | str | None:
    """Si el modelo dice haber reservado o registrado algo que no hizo.

    Pasó con el modelo real: "Le reservé el turno de Licencia de conducir por
    primera vez", sin llamar a ninguna herramienta y con una agenda que no
    existe. Si lo que pidió el ciudadano alcanza para reservar (una agenda
    nombrada y un día y una hora), se hace la reserva de verdad con esos datos;
    si no, se le dice que todavía no quedó hecho. None si no hay nada que
    corregir.
    """
    texto = _texto(respuesta)
    if _CONFIRMA_RESERVA.search(texto) and "crear_reserva" not in resultado_ejecucion:
        agenda = agenda_nombrada(await listar_agendas(db), dichos)
        fecha_hora = ultima_fecha_hora_dicha(dichos)
        logger.warning("ejecutor: el modelo confirmó una reserva que no hizo")
        if agenda is None or fecha_hora is None:
            return NO_QUEDO_RESERVADO
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "crear_reserva",
                    "args": {"turno": agenda.nombre, "fecha_hora": fecha_hora},
                    "id": "reserva_pedida_por_el_ciudadano",
                }
            ],
        )
    if _CONFIRMA_RECLAMO.search(texto) and "crear_reclamo" not in resultado_ejecucion:
        logger.warning("ejecutor: el modelo confirmó un reclamo que no registró")
        return NO_QUEDO_REGISTRADO
    return None


def dni_dicho(documento: str, dichos_del_ciudadano: list[str]) -> bool:
    """Si el DNI que propone el modelo aparece en lo que escribió el ciudadano.

    Se comparan solo los dígitos: el ciudadano escribe "30.111.295" o "30111295"
    y el modelo lo pasa sin puntos.
    """
    digitos = re.sub(r"\D", "", documento)
    if len(digitos) < 7:
        return False
    # Cada número por separado: pegar todas las cifras del mensaje haría que una
    # dirección y un teléfono juntos "contengan" un DNI que nadie escribió.
    numeros = {
        numero.replace(".", "")
        for dicho in dichos_del_ciudadano
        for numero in re.findall(r"\d[\d.]*", dicho)
    }
    # Y los DNI con guiones o espacios, como los transcribe el canal de voz.
    numeros |= {
        re.sub(r"\D", "", coincidencia.group(0))
        for dicho in dichos_del_ciudadano
        for coincidencia in DNI.finditer(dicho)
    }
    return digitos in numeros


_VUELVE_A_PEDIR_DATOS = re.compile(r"nombre completo|su DNI|número de documento", re.IGNORECASE)

CORRECCION_YA_IDENTIFICADO = (
    "(Nota interna, no la repitas: el ciudadano ya está identificado, no le pidas su "
    "nombre ni su DNI. Respondé lo que pregunta con la información que tengas; si no "
    "la tenés, decíselo.)"
)
NO_TENGO_ESE_DATO = (
    "No tengo ese dato en este momento. Si quiere, lo derivo a una persona del equipo "
    "para que se lo confirme."
)

DERIVAR = "derivar"


def _cierre_sin_modelo(exitosas: list[tuple[dict, dict]], canal: Canal) -> str | None:
    """Cómo termina el turno cuando las herramientas ya resolvieron todo.

    Una derivación pasa directo al escalado: la respuesta del modelo después de
    `derivar_a_operador` se descartaba igual. Un reclamo o una reserva creados
    se confirman con los datos reales (ver `app/agents/confirmacion.py`). Si
    hubo una consulta de estado, la respuesta la sigue redactando el modelo,
    porque depende de lo que encontró.
    """
    nombres = [llamada["name"] for llamada, _ in exitosas]
    if "derivar_a_operador" in nombres:
        return DERIVAR
    if "consultar_estado_caso" in nombres:
        return None
    confirmaciones = [
        texto
        for llamada, salida in exitosas
        if (texto := confirmacion(llamada["name"], llamada["args"], salida, canal))
    ]
    if not confirmaciones:
        return None
    identidad = next(
        (salida for llamada, salida in exitosas if llamada["name"] == "registrar_identidad"),
        None,
    )
    prefijo = agradecimiento(identidad) if identidad else ""
    return prefijo + "\n\n".join(confirmaciones)


async def _registrar_identidad_del_mensaje(
    state: AgentState, db: AsyncSession
) -> tuple[AgentState, tuple[dict, dict] | None]:
    """Si quien no está identificado manda su nombre y su DNI, se registran acá,
    sin el modelo (ver `app/agents/identidad.py`)."""
    if state.get("identificado") or not state.get("ciudadano_id"):
        return state, None
    datos = extraer_identidad(state["mensaje"])
    if datos is None or datos[0] is None:
        return state, None
    nombre, documento = datos
    ciudadano = await ciudadanos.identificar_ciudadano(
        db, uuid.UUID(state["ciudadano_id"]), documento=documento, nombre=nombre
    )
    llamada = {"name": "registrar_identidad", "args": {"nombre_completo": nombre, "documento": documento}}
    salida = {"identificado": True, "nombre": ciudadano.nombre, "documento": ciudadano.documento}
    # Si el DNI ya era de otra persona, el contacto se sumó a ella: lo que siga
    # en este turno (el reclamo pendiente) se gestiona a su nombre.
    nuevo = {**state, "ciudadano_id": str(ciudadano.id), "identificado": True, "recien_identificado": True}
    return nuevo, (llamada, salida)


_PREGUNTA_POR_SU_CASO = re.compile(
    r"\bc[oó]mo (?:va|sigue|anda|viene)\b|\bestado de\b|\bnovedad|\bqu[eé] pas[oó] con\b"
    r"|\ben qu[eé] (?:qued[oó]|est[aá])\b",
    re.IGNORECASE,
)


async def _estado_al_sumar_contacto(
    state: AgentState, db: AsyncSession, identidad: tuple[dict, dict]
) -> dict | None:
    """Quien preguntó por su caso desde un canal nuevo y recién ahí dio un DNI
    que ya existía: su contacto se acaba de sumar a esa persona, y lo que quería
    saber es el estado de sus casos.

    Se responde acá y no con el modelo. En las pruebas sobre el sistema
    completo, el modelo tomaba el "¿cómo va el reclamo del pozo?" del historial
    como un reclamo nuevo: inventaba una dirección, el control la frenaba y el
    caso terminaba derivado a un operador (caso funcional F5).
    """
    if not state.get("caso_id"):
        return None
    caso = await db.get(Caso, uuid.UUID(state["caso_id"]))
    # Solo cuando la pregunta pendiente era por sus casos: si había contado un
    # reclamo o pedido un turno, eso lo sigue gestionando el modelo. No alcanza
    # con el tipo del caso: el intake llegó a clasificar "¿cómo va el reclamo
    # del pozo?" como reclamo, por la palabra.
    if caso is None:
        return None
    ultimo_del_agente = next(
        (
            e.get("contenido") or ""
            for e in reversed(state.get("historial") or [])
            if e.get("actor") != ActorInteraccion.ciudadano.value
        ),
        "",
    )
    ultimo_del_ciudadano = next(
        (
            e.get("contenido") or ""
            for e in reversed(state.get("historial") or [])
            if e.get("actor") == ActorInteraccion.ciudadano.value
        ),
        "",
    )
    if not (
        caso.tipo == TipoCaso.consulta
        or MARCA_PEDIDO_PARA_CONSULTA in ultimo_del_agente
        or _PREGUNTA_POR_SU_CASO.search(ultimo_del_ciudadano)
    ):
        return None
    if caso.tipo != TipoCaso.consulta:
        # El caso de esta conversación se abrió con el tipo que adivinó el
        # intake; era una pregunta por el estado, no un reclamo nuevo, y así
        # tiene que verlo el operador en el panel.
        caso.tipo = TipoCaso.consulta
    pregunta = " ".join(
        e.get("contenido") or ""
        for e in state.get("historial") or []
        if e.get("actor") == ActorInteraccion.ciudadano.value
    )
    salida = await consultas.consultar_estado_caso(
        db,
        ciudadano_id=uuid.UUID(state["ciudadano_id"]),
        referencia=pregunta or None,
        excluir=caso.id,
    )
    # La unión de contactos queda hecha aunque la consulta no escriba nada.
    await db.commit()
    canal = Canal(state["canal"])
    contacto = "este correo" if canal == Canal.email else "este número"
    llamada, salida_identidad = identidad
    return {
        "resultado_ejecucion": {llamada["name"]: salida_identidad, "consultar_estado_caso": salida},
        "caso_id": state["caso_id"],
        "ciudadano_id": state["ciudadano_id"],
        "identificado": True,
        "respuesta": agradecimiento(salida_identidad)
        + f"Ya sumé {contacto} a su registro.\n\n"
        + estado_de_casos(salida, canal),
    }


async def nodo_ejecutor(state: AgentState, db: AsyncSession) -> dict:
    if ofrece_dato_sensible(state["mensaje"]):
        # Ni el modelo ni un operador tienen que recibir una clave: se contesta
        # con un texto fijo y no se sigue con el pedido de este mensaje.
        return {
            "resultado_ejecucion": None,
            "caso_id": state.get("caso_id"),
            "respuesta": respuesta_dato_sensible(bool(state.get("identificado"))),
        }
    gestion = await atender_turno(state, db)
    if gestion is not None:
        return gestion
    antes = state.get("ciudadano_id")
    state, identidad = await _registrar_identidad_del_mensaje(state, db)
    if identidad and state.get("ciudadano_id") != antes:
        resultado = await _estado_al_sumar_contacto(state, db, identidad)
        if resultado is not None:
            return resultado
    resultado = await _resolver(state, db, identidad)
    if state.get("recien_identificado"):
        resultado = {**resultado, "ciudadano_id": state["ciudadano_id"], "identificado": True}
        respuesta = resultado.get("respuesta")
        datos = identidad[1] if identidad else {}
        if respuesta and _VUELVE_A_PEDIR_DATOS.search(respuesta):
            # Acaba de darlos: volver a pedírselos es lo peor que puede pasar en
            # este punto. Pasó en una prueba, después de que el control de datos
            # inventados frenara un reclamo y el modelo se desorientara.
            resultado["respuesta"] = agradecimiento(datos) + "Ya registré sus datos. ¿En qué lo puedo ayudar?"
        elif respuesta and datos:
            nombre = (datos.get("nombre") or "").split()
            if nombre and nombre[0].lower() not in respuesta.lower():
                resultado["respuesta"] = agradecimiento(datos) + respuesta
    respuesta = resultado.get("respuesta")
    if respuesta and _REFERENCIA.search(respuesta):
        permitidas = await _referencias_del_ciudadano(
            db, resultado.get("ciudadano_id") or state.get("ciudadano_id")
        )
        resultado = {**resultado, "respuesta": sin_referencias_ajenas(respuesta, permitidas)}
    respuesta = resultado.get("respuesta")
    if respuesta:
        conocido = " ".join(
            [state["mensaje"]] + [e.get("contenido") or "" for e in state.get("historial") or []]
        )
        resultado = {**resultado, "respuesta": sin_nombre_inventado(respuesta, conocido)}
    return resultado


async def _resolver(
    state: AgentState, db: AsyncSession, identidad: tuple[dict, dict] | None
) -> dict:
    tools = construir_tools(db, state)
    tools_por_nombre = {t.name: t for t in tools}
    modelo = llm.get_llm_ejecutor().bind_tools(tools)

    # El historial del caso entra como turnos previos de la conversación. Sin
    # esto el ejecutor solo ve el mensaje actual y le vuelve a preguntar al
    # ciudadano algo que ya dijo antes, que es justamente lo que el proyecto
    # busca evitar. El nodo de contexto ya lo trae sin las notas internas.
    mensajes: list = [
        SystemMessage(
            content=prompt_del_sistema(
                Canal(state["canal"]),
                conocimiento=state.get("conocimiento"),
                pautas=state.get("pautas"),
                origen_menu=state.get("origen_menu"),
                # Mismo criterio que `construir_tools` para ofrecer
                # `registrar_identidad`: sin el dato, no está identificado.
                identificado=bool(state.get("identificado")),
            )
        )
    ]
    for entrada in state.get("historial") or []:
        contenido = entrada.get("contenido") or ""
        if not contenido:
            continue
        if entrada.get("actor") == ActorInteraccion.ciudadano.value:
            mensajes.append(HumanMessage(content=contenido))
        else:
            # Agente u operador: para el ciudadano, los dos son el organismo.
            mensajes.append(AIMessage(content=contenido))
    mensajes.append(HumanMessage(content=state["mensaje"]))

    resultado_ejecucion: dict = {}
    caso_id = state.get("caso_id")
    fallos = 0
    identificado = bool(state.get("identificado"))
    # `identidad` guarda la identidad registrada en este mismo turno (por el
    # código o por el modelo), para que la confirmación del reclamo que sigue
    # empiece agradeciéndole por nombre.

    # Lo que escribió el ciudadano, del mensaje actual al más viejo: contra esto
    # se verifican los datos que propone el modelo.
    dichos = [state["mensaje"]] + [
        e.get("contenido") or ""
        for e in reversed(state.get("historial") or [])
        if e.get("actor") == ActorInteraccion.ciudadano.value
    ]

    corregido = False
    for _ in range(MAX_ITERACIONES):
        respuesta_llm: AIMessage = await modelo.ainvoke(mensajes)

        if not respuesta_llm.tool_calls:
            corregida = await _sin_confirmaciones_inventadas(
                respuesta_llm, db, resultado_ejecucion, dichos
            )
            if isinstance(corregida, str):
                return {
                    "resultado_ejecucion": resultado_ejecucion or None,
                    "caso_id": caso_id,
                    "respuesta": corregida,
                }
            if corregida is not None:
                respuesta_llm = corregida

        if not respuesta_llm.tool_calls:
            derivacion = resultado_ejecucion.get("derivar_a_operador")
            if derivacion:
                return {
                    "resultado_ejecucion": resultado_ejecucion,
                    "caso_id": caso_id,
                    "requiere_escalado": True,
                    "motivo_escalado": "sin_herramienta",
                }
            texto = _texto(respuesta_llm)
            # Quien se identificó en este mismo mensaje tiene su propio arreglo
            # en `nodo_ejecutor` (el agradecimiento y "ya registré sus datos").
            if identificado and not state.get("recien_identificado") and _VUELVE_A_PEDIR_DATOS.search(texto):
                # Pasó con la v3: ya identificada por correo, Laura preguntó
                # para cuándo arreglaban el pozo y el modelo le volvió a pedir
                # nombre y DNI, copiando el pedido que tenía en el historial.
                # Se le corrige una vez; si insiste, va un texto fijo.
                if not corregido:
                    corregido = True
                    mensajes.append(respuesta_llm)
                    mensajes.append(HumanMessage(content=CORRECCION_YA_IDENTIFICADO))
                    continue
                texto = NO_TENGO_ESE_DATO
            return {
                "resultado_ejecucion": resultado_ejecucion or None,
                "caso_id": caso_id,
                "respuesta": texto,
            }

        mensajes.append(respuesta_llm)
        # Lo que el modelo escribe junto con la llamada (un aviso de emergencia,
        # por ejemplo, si una pauta del organismo lo pide) se conserva delante
        # de la confirmación armada por código, salvo que afirme algo hecho o
        # nombre un número de caso: eso lo dice solo la confirmación.
        aviso_previo = _texto(respuesta_llm)
        if _CONFIRMA_RESERVA.search(aviso_previo) or _CONFIRMA_RECLAMO.search(aviso_previo) or _REFERENCIA.search(aviso_previo):
            aviso_previo = ""
        exitosas: list[tuple[dict, dict]] = []
        hubo_fallo = False
        # La identidad primero: si en el mismo mensaje dio sus datos y el
        # reclamo, el reclamo tiene que quedar a su nombre y no al provisorio.
        llamadas = sorted(
            respuesta_llm.tool_calls, key=lambda c: c["name"] != "registrar_identidad"
        )
        gestionadas: set[str] = set()
        for tool_call in llamadas:
            if tool_call["name"] == "crear_reclamo" and await _es_pedido_de_turno(state, db, dichos):
                # Pasó por voz con la v3: pidió un turno, dio su DNI y el
                # modelo registró un reclamo con el pedido del turno como
                # descripción. Se trata como lo que es; si todavía no dijo el
                # día, el control de `crear_reserva` se lo pregunta.
                logger.warning("ejecutor: crear_reclamo en un pedido de turno; va como reserva")
                agenda = agenda_nombrada(await listar_agendas(db), dichos)
                tool_call["name"] = "crear_reserva"
                tool_call["args"] = {
                    "turno": agenda.nombre if agenda else "",
                    "fecha_hora": ultima_fecha_hora_dicha(dichos) or "",
                }
            if tool_call["name"] in GESTIONES and tool_call["name"] in gestionadas:
                # Pasó con la v3: dos `crear_reclamo` en la misma respuesta, con
                # dos redacciones del mismo pozo. Caen en el mismo caso de la
                # conversación y el ciudadano recibía la confirmación dos veces.
                logger.warning("ejecutor: se ignora un segundo %s en la misma respuesta", tool_call["name"])
                continue
            if tool_call["name"] in GESTIONES and not identificado:
                # La instrucción del prompt pide los datos antes de gestionar,
                # pero el modelo a veces crea el reclamo igual. Acá no depende
                # de que obedezca: sin DNI no se crea nada y se le piden los
                # datos. El mensaje queda en el caso, así que en el próximo
                # turno, ya identificado, el modelo retoma la gestión.
                return {
                    "resultado_ejecucion": resultado_ejecucion or None,
                    "caso_id": caso_id,
                    "respuesta": pedido_de_identificacion(
                        tool_call["name"], Canal(state["canal"])
                    ),
                }
            herramienta = tools_por_nombre.get(tool_call["name"])
            if tool_call["name"] == "registrar_identidad" and not dni_dicho(
                tool_call["args"].get("documento") or "", dichos
            ):
                # Pasó en una prueba: ante una mordedura, el modelo registró a
                # un "Juan" que nadie nombró. Con un DNI inventado que fuera de
                # otra persona, el contacto se sumaría a ella y vería sus casos.
                logger.warning("ejecutor: registrar_identidad con un DNI que el ciudadano no dio")
                mensajes.append(
                    ToolMessage(
                        content=json.dumps(
                            {
                                "error": "El ciudadano todavía no informó ese DNI. No lo "
                                "inventes: pedile su nombre completo y su DNI."
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call["id"],
                    )
                )
                hubo_fallo = True
                continue
            if tool_call["name"] == "crear_reserva":
                agendas = await listar_agendas(db)
                nombrada = agenda_nombrada(agendas, dichos)
                if nombrada is not None and nombrada.nombre != tool_call["args"].get("turno"):
                    logger.warning(
                        "ejecutor: el modelo pidió '%s' y el ciudadano nombró '%s'",
                        tool_call["args"].get("turno"),
                        nombrada.nombre,
                    )
                    tool_call["args"]["turno"] = nombrada.nombre
                # El día y la hora que dijo el ciudadano mandan sobre los que
                # propone el modelo, que a veces se equivoca de fecha.
                pedida = ultima_fecha_hora_dicha(dichos)
                if pedida is not None and pedida != tool_call["args"].get("fecha_hora"):
                    tool_call["args"]["fecha_hora"] = pedida
                if not dijo_un_dia(dichos):
                    # Nunca dijo un día: la fecha la inventó el modelo. Se le
                    # pregunta, con la grilla de la agenda a la vista.
                    libres = (
                        await proximos_horarios_libres(db, nombrada) if nombrada is not None else []
                    )
                    return {
                        "resultado_ejecucion": resultado_ejecucion or None,
                        "caso_id": caso_id,
                        "respuesta": pedido_de_dia_y_hora(nombrada, Canal(state["canal"]), libres),
                    }
            if tool_call["name"] == "crear_reclamo":
                inventados = datos_inventados(tool_call["args"].get("descripcion") or "", dichos)
                propia = descripcion_del_ciudadano(tool_call["args"].get("descripcion") or "", dichos) if inventados else None
                if propia:
                    # Pasó con la v3: después de identificarse, el modelo le
                    # agregó al pozo de Rivadavia tres calles que nadie dijo, el
                    # control lo frenó y al reintentar volvió a inventar y
                    # derivó. Si el ciudadano ya contó el problema, se registra
                    # con sus palabras, que no pueden tener nada inventado.
                    logger.warning("ejecutor: descripción con datos no dichos %s; va la del ciudadano", inventados)
                    tool_call["args"]["descripcion"] = propia
                    inventados = []
                if inventados:
                    # No se ejecuta: el modelo recibe el motivo y pregunta en
                    # vez de registrar un reclamo con datos que nadie dio.
                    logger.warning("ejecutor: descripción con datos no dichos: %s", inventados)
                    hubo_fallo = True
                    fallos += 1
                    if fallos > MAX_FALLOS:
                        return {
                            "resultado_ejecucion": resultado_ejecucion or None,
                            "caso_id": caso_id,
                            "requiere_escalado": True,
                            "motivo_escalado": "fallo_ejecucion",
                        }
                    mensajes.append(
                        ToolMessage(
                            content=json.dumps(
                                {
                                    "error": "La descripción incluye datos que el ciudadano no dio: "
                                    + ", ".join(inventados)
                                    + ". No inventes datos: preguntale lo que falta o usá solo lo que dijo."
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id=tool_call["id"],
                        )
                    )
                    continue
            try:
                if herramienta is None:
                    raise ValueError(f"herramienta no ofrecida: {tool_call['name']}")
                salida = await herramienta.ainvoke(tool_call["args"])
            except ReservaNoDisponible as error:
                # No es una falla: el horario está ocupado, ya pasó o no existe
                # en la agenda. Se le ofrecen los libres más cercanos con datos
                # reales, sin pasar por el modelo, que podría inventar horarios.
                return {
                    "resultado_ejecucion": resultado_ejecucion or None,
                    "caso_id": caso_id,
                    "respuesta": horario_no_disponible(
                        error.motivo,
                        error.alternativas,
                        error.vigente,
                        Canal(state["canal"]),
                        pedido=reservas.leer_fecha_hora(tool_call["args"].get("fecha_hora") or ""),
                    ),
                }
            except Exception:
                logger.exception("ejecutor: fallo la tool %s", tool_call["name"])
                hubo_fallo = True
                fallos += 1
                if fallos > MAX_FALLOS:
                    return {
                        "resultado_ejecucion": resultado_ejecucion or None,
                        "caso_id": caso_id,
                        "requiere_escalado": True,
                        "motivo_escalado": "fallo_ejecucion",
                    }
                salida = {"error": "La acción falló, intente de otra forma."}
            else:
                exitosas.append((tool_call, salida if isinstance(salida, dict) else {}))
                gestionadas.add(tool_call["name"])
                if tool_call["name"] == "registrar_identidad":
                    identificado = True
                    identidad = exitosas[-1]
                    # Si el DNI ya existía, el contacto se sumó a esa persona:
                    # las herramientas que sigan tienen que actuar a su nombre.
                    actual = await obtener_ciudadano_por_canal(
                        db, Canal(state["canal"]), state["identificador"]
                    )
                    if actual is not None and str(actual.id) != state["ciudadano_id"]:
                        state = {**state, "ciudadano_id": str(actual.id), "identificado": True, "recien_identificado": True}
                        tools = construir_tools(db, state)
                        tools_por_nombre = {t.name: t for t in tools}
                        modelo = llm.get_llm_ejecutor().bind_tools(tools)

            if (
                tool_call["name"] == "consultar_estado_caso"
                and not identificado
                and isinstance(salida, dict)
                and not salida.get("tiene_casos")
            ):
                # Un contacto nuevo que pregunta por "el reclamo del pozo" lo
                # inició por otro canal: contestarle "no encontré casos a su
                # nombre" es falso. Se le piden los datos, y con el DNI se
                # suma el contacto y se le da el estado (caso funcional F5).
                return {
                    "resultado_ejecucion": resultado_ejecucion or None,
                    "caso_id": caso_id,
                    "respuesta": pedido_de_identificacion_para_consulta(Canal(state["canal"])),
                }
            if isinstance(salida, dict):
                resultado_ejecucion[tool_call["name"]] = salida
                caso_id = salida.get("caso_id", caso_id)
            mensajes.append(
                ToolMessage(
                    content=json.dumps(salida, default=str, ensure_ascii=False),
                    tool_call_id=tool_call["id"],
                )
            )

        if hubo_fallo:
            # El modelo ve el error y decide: corregir el dato, preguntar o derivar.
            continue
        if identidad is not None and identidad not in exitosas:
            exitosas.insert(0, identidad)
        cierre = _cierre_sin_modelo(exitosas, Canal(state["canal"]))
        if cierre == DERIVAR:
            return {
                "resultado_ejecucion": resultado_ejecucion,
                "caso_id": caso_id,
                "requiere_escalado": True,
                "motivo_escalado": "sin_herramienta",
            }
        if cierre:
            return {
                "resultado_ejecucion": resultado_ejecucion,
                "caso_id": caso_id,
                "respuesta": f"{aviso_previo}\n\n{cierre}" if aviso_previo else cierre,
            }

    return {
        "resultado_ejecucion": resultado_ejecucion or None,
        "caso_id": caso_id,
        "requiere_escalado": True,
        "motivo_escalado": "iteraciones_agotadas",
    }
