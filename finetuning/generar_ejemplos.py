"""Genera un banco grande de ejemplos de tool calling combinando plantillas
de frase con bancos de variación (barrios, calles, problemas, fechas) — en
vez de escribir a mano cada ejemplo uno por uno, como se hizo con los 47
originales de `ejemplos_tool_calling.jsonl`.

Por qué por separado y no mezclado con los 47 originales: los 47 los revisé
uno por uno a mano; estos salen de combinar plantillas, así que la calidad de
cada uno individual no tiene la misma revisión. Separarlos en
`fuente="manual_generado"` (vs. `"manual"`) deja esa distinción trazable en
el dataset, en vez de hacer parecer que los 250+ se escribieron y revisaron
uno por uno igual que los primeros 47. Ver DEVLOG.md
("Ejemplos generados por plantilla").

Todos los datos (nombres de calles, barrios, importes, números de caso) son
ficticios — igual que el resto de los datos de demo del proyecto.

Uso: .venv/Scripts/python.exe generar_ejemplos.py
Salida: ejemplos_generados.jsonl (en la raíz de finetuning/, versionado)
"""
import json
import random
from pathlib import Path

from esquema import EjemploEntrenamiento

SEMILLA = 123
SALIDA = Path(__file__).parent / "ejemplos_generados.jsonl"

random.seed(SEMILLA)

BARRIOS = [
    "Palermo", "Belgrano", "Caballito", "Flores", "Villa Urquiza",
    "Villa Crespo", "Almagro", "Boedo", "San Telmo", "Retiro", "Núñez",
    "Colegiales", "Chacarita", "Villa Devoto", "Mataderos", "Liniers",
    "Floresta", "Parque Patricios", "Barracas", "Constitución", "Balvanera",
    "Villa del Parque", "Villa Pueyrredón", "Saavedra", "Coghlan",
    "Monte Castro", "Versalles", "Villa Luro", "Agronomía", "Paternal",
]

CALLES = [
    "Av. Rivadavia", "Av. Corrientes", "Av. Santa Fe", "Av. Cabildo",
    "Av. Directorio", "Av. Juan B. Justo", "Av. San Martín", "Av. Warnes",
    "Av. Triunvirato", "Av. de los Incas", "Av. Pedro Goyena", "Av. La Plata",
    "Av. Boedo", "Humboldt", "Thames", "Honduras", "Jorge Newbery",
    "Gurruchaga", "Serrano", "Nicaragua", "Soler", "Costa Rica", "Bonpland",
    "Scalabrini Ortiz", "Medrano", "Av. Belgrano", "Av. Independencia",
]


def direccion() -> str:
    texto = f"{random.choice(CALLES)} {random.randint(100, 6800)}"
    if random.random() < 0.4:
        texto += f", {random.choice(BARRIOS)}"
    return texto


def cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def descap(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


# (frase coloquial del ciudadano, frase formal para descripcion/respuesta)
PROBLEMAS_INFRA = [
    ("se cayó un árbol y bloquea la vereda", "Árbol caído bloqueando la vereda"),
    ("hay un poste de luz quemado hace una semana", "Poste de luz quemado"),
    ("hay un pozo enorme en el medio de la calle", "Pozo en la calzada"),
    ("el semáforo no funciona desde ayer", "Semáforo fuera de servicio"),
    ("se rompió la vereda y es peligroso caminar", "Vereda rota, riesgo para peatones"),
    ("hay un cable de luz caído", "Cable de luz caído"),
    ("la tapa de una alcantarilla está rota", "Tapa de alcantarilla rota"),
    ("se rompió un caño y hay agua en la calle", "Pérdida de agua en la calzada"),
    ("no hay más foco en la plaza hace días", "Falta de iluminación en la plaza"),
    ("el desagüe está tapado y se inunda todo cuando llueve", "Desagüe tapado, inunda la calle"),
    ("se partió una rama grande y quedó colgando sobre la vereda", "Rama partida colgando sobre la vereda"),
    ("hay un bache enorme que ya rompió varias ruedas", "Bache profundo en la calzada"),
    ("hay un contenedor de reciclaje roto y desbordado", "Contenedor de reciclaje roto y desbordado"),
    ("se rompió una boca de tormenta y sale un olor muy fuerte", "Boca de tormenta rota con olor fuerte"),
    ("hay grafitis en toda la pared de la plaza", "Grafitis en la pared de la plaza"),
    ("se rompió la rampa para sillas de ruedas de la esquina", "Rampa de accesibilidad rota"),
    ("hay escombros de una obra tirados en la vereda hace días", "Escombros de obra abandonados en la vereda"),
    ("el cartel de la calle está caído y tapa el paso", "Cartel de señalización caído"),
    ("hay un árbol totalmente seco que se puede caer en cualquier momento", "Árbol seco en riesgo de caída"),
    ("se inundó la esquina por la lluvia y no baja el agua", "Esquina inundada, el agua no baja"),
    ("falta una tapa de inspección en la vereda y de noche es peligroso", "Falta tapa de inspección en la vereda"),
]

PROBLEMAS_SERVICIO = [
    ("no pasa el camión de la basura hace {n} días", "No pasa el camión de recolección de basura hace {n} días"),
    ("no barren la cuadra hace semanas", "Falta de barrido en la cuadra"),
    ("no podaron los árboles y las ramas tapan la luz de la calle", "Falta de poda, las ramas tapan el alumbrado"),
    ("los contenedores de basura están desbordados", "Contenedores de basura desbordados"),
    ("no vinieron a desratizar como habían prometido", "Desratización prometida sin realizar"),
    ("el servicio de recolección de residuos está todo mal últimamente", "Problemas recurrentes con la recolección de residuos"),
    ("se juntó mucha basura en la plaza y nadie la levanta", "Acumulación de basura sin recolectar en la plaza"),
    ("hace ruido todo el día una obra que no tiene horario autorizado", "Ruidos molestos de obra fuera de horario permitido"),
    ("los caniles para perros están todos rotos", "Caniles municipales rotos"),
    ("no funcionan las luces del playón deportivo hace semanas", "Falta de iluminación en el playón deportivo"),
    ("no limpiaron los pasillos del mercado municipal hace mucho", "Falta de limpieza en el mercado municipal"),
]

PROBLEMAS_TRAMITE_RECLAMO = [
    ("pagué la tasa de ABL y me sigue apareciendo como deuda", "Pago de la tasa de ABL no reflejado en el sistema"),
    ("me cobraron dos veces la misma tasa", "Cobro duplicado de una tasa municipal"),
    ("hice un trámite hace {n} semanas y todavía no tengo respuesta", "Trámite sin respuesta desde hace {n} semanas"),
    ("me rechazaron un trámite sin ninguna explicación", "Rechazo de un trámite sin justificación"),
    ("no me llega la boleta de ABL hace meses", "Boleta de ABL no recibida hace meses"),
    ("me descontaron una multa que ya había pagado", "Descuento de una multa ya abonada"),
    ("no me reconocen un pago de tasa que hice por home banking", "Pago de tasa por home banking no reconocido"),
    ("me generaron una deuda que no me corresponde", "Deuda generada incorrectamente"),
    ("no puedo acceder a mi expediente online aunque lo inicié hace {n} semanas", "Expediente iniciado sin acceso online disponible desde hace {n} semanas"),
]

LOCADORES_VAGOS = [
    "cerca de mi casa", "en mi cuadra", "en mi calle", "frente a mi casa",
    "a la vuelta de mi casa", "en la esquina de mi casa", "en mi barrio",
]

RESPUESTAS_RECLAMO_INCOMPLETO = [
    "Para registrar el reclamo necesito la dirección exacta. ¿Me la puede indicar?",
    "¿Me puede pasar la dirección exacta? Así registro el reclamo.",
    "Para poder registrarlo necesito que me diga la calle y la altura exactas.",
]

PLANTILLAS_RECLAMO_COMPLETO = [
    "{frase} en {direccion}",
    "Hola, {frase} en {direccion}",
    "Quería avisar que {frase} en {direccion}",
    "Buenas, {frase} en {direccion}, ¿lo pueden solucionar?",
    "Necesito hacer un reclamo, {frase} en {direccion}",
    "Disculpen, {frase} en {direccion}",
    "Buen día, {frase} en {direccion}",
    "{frase} en {direccion}, ¿cuánto tardan en solucionarlo?",
    "Quiero reportar que {frase} en {direccion}",
]


def generar_reclamos_con_direccion(banco, categoria, n_por_problema):
    ejemplos = []
    for frase, formal in banco:
        for _ in range(n_por_problema):
            n = random.choice([3, 4, 5, 6, 8, 10])
            frase_i = frase.format(n=n)
            formal_i = formal.format(n=n)
            dire = direccion()
            plantilla = random.choice(PLANTILLAS_RECLAMO_COMPLETO)
            instruccion = cap(plantilla.format(frase=frase_i, direccion=dire))
            descripcion = f"{formal_i} en {dire}"
            respuesta = f"Registré su reclamo por {descap(formal_i)} en {dire}."
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="reclamo",
                    confianza=round(random.uniform(0.88, 0.96), 2),
                    llamada_herramienta={
                        "nombre": "crear_reclamo",
                        "parametros": {"descripcion": descripcion, "categoria": categoria},
                    },
                    respuesta=respuesta,
                    fuente="manual_generado",
                )
            )
    return ejemplos


def generar_reclamos_incompletos(banco, n_por_problema):
    ejemplos = []
    for frase, _ in banco:
        for _ in range(n_por_problema):
            n = random.choice([3, 4, 5, 6, 8, 10])
            frase_i = frase.format(n=n)
            locador = random.choice(LOCADORES_VAGOS)
            instruccion = cap(f"{frase_i} {locador}")
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="reclamo",
                    confianza=round(random.uniform(0.75, 0.88), 2),
                    llamada_herramienta=None,
                    respuesta=random.choice(RESPUESTAS_RECLAMO_INCOMPLETO),
                    fuente="manual_generado",
                )
            )
    return ejemplos


def generar_reclamos_tramite():
    """Categoría de reclamo 'tramite' (CategoriaReclamo): no necesita
    dirección, así que casi todos quedan completos."""
    ejemplos = []
    for frase, formal in PROBLEMAS_TRAMITE_RECLAMO:
        for _ in range(6):
            n = random.choice([2, 3, 4, 6])
            frase_i = frase.format(n=n)
            formal_i = formal.format(n=n)
            plantilla = random.choice([
                "{frase}", "Hola, {frase}", "Buenas, {frase}, ¿qué hago?",
                "Quería reclamar: {frase}", "Disculpen, {frase}",
                "{frase}, ¿qué puedo hacer?",
            ])
            instruccion = cap(plantilla.format(frase=frase_i))
            respuesta = random.choice([
                f"Registré su reclamo por {descap(formal_i)}. Le van a pedir el comprobante para resolverlo.",
                f"Le registré el reclamo por {descap(formal_i)}. Un operador va a revisar el caso.",
            ])
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="reclamo",
                    confianza=round(random.uniform(0.82, 0.92), 2),
                    llamada_herramienta={
                        "nombre": "crear_reclamo",
                        "parametros": {"descripcion": formal_i, "categoria": "tramite"},
                    },
                    respuesta=respuesta,
                    fuente="manual_generado",
                )
            )
    vagos = [
        "Hice un trámite hace tiempo y no tengo respuesta",
        "Tengo un problema con un pago de una tasa",
        "Me cobraron algo mal y no sé a quién reclamarle",
        "Tengo un problema con una boleta y no sé cómo resolverlo",
        "Hay un error en mi cuenta con el organismo",
    ]
    for texto in vagos:
        ejemplos.append(
            EjemploEntrenamiento(
                instruccion=texto,
                intencion="reclamo",
                confianza=0.65,
                llamada_herramienta=None,
                respuesta="¿Me puede contar de qué trámite o pago se trata, para poder registrar el reclamo correctamente?",
                fuente="manual_generado",
            )
        )
    return ejemplos


TURNOS = ["DNI", "licencia de conducir", "CeSAC"]

FECHAS = [
    ("el lunes 3 de noviembre a las 10", "2026-11-03 10:00"),
    ("el martes 4 de noviembre a las 15:30", "2026-11-04 15:30"),
    ("15/11 a las 14 hs", "2026-11-15 14:00"),
    ("el 20 de noviembre a las 9 de la mañana", "2026-11-20 09:00"),
    ("miércoles 18 a las 16", "2026-11-18 16:00"),
    ("el 2 de diciembre a las 11:30", "2026-12-02 11:30"),
    ("jueves 5 de noviembre a las 8:45", "2026-11-05 08:45"),
    ("el 28 de noviembre a las 13", "2026-11-28 13:00"),
    ("10/12 a las 10:15", "2026-12-10 10:15"),
    ("el viernes 6 de noviembre a las 17", "2026-11-06 17:00"),
    ("el lunes que viene a las 9:30", "2026-11-10 09:30"),
    ("el 1 de diciembre a las 12", "2026-12-01 12:00"),
    ("el 9 de noviembre a las 10:45", "2026-11-09 10:45"),
    ("el 23 de noviembre a las 15", "2026-11-23 15:00"),
    ("martes 24 a las 8:30", "2026-11-24 08:30"),
    ("el 30 de noviembre a las 12:15", "2026-11-30 12:15"),
    ("5 de diciembre a las 9", "2026-12-05 09:00"),
    ("el lunes 16 de noviembre a las 11", "2026-11-16 11:00"),
]

PLANTILLAS_RESERVA_COMPLETA = [
    "Necesito un turno para {turno}, {fecha}",
    "Quiero sacar un turno de {turno} para {fecha}",
    "¿Me pueden dar un turno para {turno}, {fecha}?",
    "Quiero reservar para {turno}, {fecha}",
    "Turno para {turno}, {fecha}",
    "Necesito reservar {turno} para {fecha}",
    "Hola, necesito un turno de {turno} para {fecha}",
    "Buenas, ¿tienen un turno de {turno} para {fecha}?",
    "Quisiera un turno para {turno}, {fecha}",
]


def generar_reservas_completas(n_por_turno):
    ejemplos = []
    for turno in TURNOS:
        for _ in range(n_por_turno):
            fecha_texto, fecha_iso = random.choice(FECHAS)
            plantilla = random.choice(PLANTILLAS_RESERVA_COMPLETA)
            instruccion = cap(plantilla.format(turno=turno, fecha=fecha_texto))
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="reserva",
                    confianza=round(random.uniform(0.85, 0.94), 2),
                    llamada_herramienta={
                        "nombre": "crear_reserva",
                        "parametros": {"turno": turno, "fecha_hora": fecha_iso},
                    },
                    respuesta=f"Le reservé el turno de {turno} para {fecha_texto}.",
                    fuente="manual_generado",
                )
            )
    return ejemplos


def generar_reservas_incompletas(n_por_turno):
    ejemplos = []
    plantillas = [
        "Quiero sacar un turno para {turno}",
        "Necesito un turno de {turno}, ¿cómo hago?",
        "¿Tienen turno para {turno}?",
        "Quiero el turno de {turno} para la semana que viene",
        "Hola, necesito un turno de {turno}",
        "Buenas, quería pedir un turno de {turno}",
    ]
    respuestas = [
        "¿Qué día y horario le queda bien para el turno de {turno}?",
        "Claro. ¿Qué día y a qué hora le queda bien para {turno}?",
        "¿Para qué día quiere el turno de {turno}? Así le confirmo el horario.",
    ]
    for turno in TURNOS:
        for _ in range(n_por_turno):
            plantilla = random.choice(plantillas)
            instruccion = cap(plantilla.format(turno=turno))
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="reserva",
                    confianza=round(random.uniform(0.75, 0.87), 2),
                    llamada_herramienta=None,
                    respuesta=random.choice(respuestas).format(turno=turno),
                    fuente="manual_generado",
                )
            )
    return ejemplos


def generar_reservas_vagas():
    textos = [
        "Necesito un turno",
        "Quiero sacar un turno, ¿para qué cosas hay?",
        "¿Me pueden dar un turno para esta semana?",
        "Necesito reservar algo pero no sé bien qué turno pedir",
        "Quiero un turno para el lunes",
    ]
    ejemplos = []
    for texto in textos:
        ejemplos.append(
            EjemploEntrenamiento(
                instruccion=texto,
                intencion="reserva",
                confianza=round(random.uniform(0.5, 0.65), 2),
                llamada_herramienta=None,
                respuesta="Claro. ¿Para qué trámite necesita el turno: DNI, licencia de conducir o CeSAC? Y qué día le queda bien.",
                fuente="manual_generado",
            )
        )
    return ejemplos


REFERENCIAS = [
    "árbol caído", "reclamo de la semana pasada", "la licencia de conducir",
    "el DNI", "REC-00123", "REC-00456", "REC-00789", "el trámite de la tasa",
    "mi reserva del CeSAC", "el pozo de la calle", "REC-00912", "REC-01045",
    "el reclamo del semáforo", "la poda del árbol", "mi reserva del DNI",
]

PLANTILLAS_CONSULTAR_ESTADO = [
    "¿Cómo va mi reclamo de {ref}?",
    "¿En qué quedó {ref}?",
    "Quiero saber el estado de {ref}",
    "¿Ya resolvieron {ref}?",
    "¿Tienen novedades de {ref}?",
    "¿Me puede decir cómo sigue {ref}?",
    "Necesito saber en qué está {ref}",
]

RESPUESTAS_CONSULTAR_ESTADO = [
    "Permítame revisar el estado de su caso.",
    "Permítame revisarlo.",
    "Un momento, reviso el estado de su caso.",
]


def generar_consultar_estado():
    ejemplos = []
    for ref in REFERENCIAS:
        for plantilla in random.sample(PLANTILLAS_CONSULTAR_ESTADO, 2):
            instruccion = cap(plantilla.format(ref=ref))
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=instruccion,
                    intencion="consulta",
                    confianza=round(random.uniform(0.8, 0.92), 2),
                    llamada_herramienta={
                        "nombre": "consultar_estado_caso",
                        "parametros": {"referencia": ref},
                    },
                    respuesta=random.choice(RESPUESTAS_CONSULTAR_ESTADO),
                    fuente="manual_generado",
                )
            )
    for texto in [
        "¿Cómo va mi caso?", "Quiero saber el estado de mi trámite",
        "¿Tienen alguna novedad de mi caso?", "¿Cómo viene mi trámite?",
    ]:
        ejemplos.append(
            EjemploEntrenamiento(
                instruccion=texto,
                intencion="consulta",
                confianza=0.7,
                llamada_herramienta={"nombre": "consultar_estado_caso", "parametros": {"referencia": ""}},
                respuesta="Permítame revisar sus casos.",
                fuente="manual_generado",
            )
        )
    return ejemplos


CONSULTAS_INFORMATIVAS = [
    ("¿Hasta qué hora atiende la oficina de atención al vecino?", "La oficina de atención al vecino atiende de 8 a 14 horas, de lunes a viernes."),
    ("¿Qué documentación necesito para renovar la licencia de conducir?", "Necesita el DNI, la licencia anterior y el certificado de aptitud psicofísica vigente."),
    ("¿Puedo pagar la tasa municipal online?", "Sí, puede pagarla desde la página del organismo con tarjeta de débito o transferencia."),
    ("¿Qué requisitos pide el organismo para habilitar un comercio?", "Necesita el certificado de uso conforme, la habilitación de bomberos y el alta de AFIP."),
    ("¿Puedo hacer un reclamo por teléfono?", "Sí, puede hacerlo por teléfono, WhatsApp o correo electrónico, como prefiera."),
    ("¿A qué número llamo si tengo una emergencia con el servicio de agua?", "Para emergencias de agua corriente puede llamar a la línea 147, disponible las 24 horas."),
    ("¿El organismo atiende los sábados?", "No, el organismo atiende de lunes a viernes. Los sábados y domingos permanece cerrado."),
    ("¿Cuánto tarda en resolverse un reclamo por alumbrado público?", "Los reclamos de alumbrado se resuelven, en general, dentro de los 10 días hábiles."),
    ("¿Dónde queda el CeSAC más cercano a Villa Urquiza?", "¿Me puede confirmar en qué calle vive? Así le indico el CeSAC más cercano."),
    ("¿Qué turnos hay disponibles para el DNI esta semana?", "Tiene turnos disponibles el martes y el jueves por la mañana. ¿Le reservo alguno?"),
    ("¿Cómo hago para dar de alta un comercio nuevo?", "Para iniciar la habilitación necesita presentar el certificado de uso conforme y la documentación del local."),
    ("¿Cuánto sale sacar una licencia de conducir nueva?", "El costo depende de la categoría. Puede consultarlo en la página del organismo o en la ventanilla."),
    ("¿Hasta cuándo tengo para pagar la tasa de ABL sin recargo?", "El vencimiento es el día 10 de cada mes. Después de esa fecha se aplica un recargo."),
    ("¿Qué pasa si no pago la tasa municipal a tiempo?", "Se le aplica un interés por mora y, si se acumula, puede derivar en un reclamo de deuda."),
    ("¿Dónde puedo reclamar por un árbol que hay que podar?", "Puede hacer el reclamo por este mismo medio, indicando la dirección exacta."),
    ("¿Cuánto tiempo tarda en estar lista la licencia de conducir?", "Una vez aprobado el trámite, la licencia suele estar lista en 5 días hábiles."),
    ("¿Se puede sacar turno para el DNI de un menor?", "Sí, pero tiene que venir acompañado por un adulto responsable con su documentación."),
    ("¿Qué pasa si pierdo el DNI?", "Tiene que hacer la denuncia de extravío y después sacar un turno para la renovación."),
    ("¿Los reclamos se pueden hacer de forma anónima?", "No, para darle seguimiento al reclamo necesitamos al menos su nombre y un contacto."),
    ("¿Puedo cambiar el día de un turno ya reservado?", "Sí, puede pedirme un nuevo turno y cancelamos el anterior."),
    ("¿El CeSAC atiende sin turno previo?", "Depende del servicio. Para consultas generales puede ir directamente, para estudios necesita turno."),
    ("¿Dónde averiguo si mi comercio ya está habilitado?", "Puede consultarlo en la oficina de habilitaciones, o decirme el nombre del comercio y reviso el trámite."),
    ("¿Qué hago si el camión de la basura no pasó por mi cuadra?", "Puede hacer un reclamo indicando la dirección y hace cuánto no pasa."),
    ("¿Los feriados el organismo atiende?", "No, los días feriados el organismo permanece cerrado."),
    ("¿Puedo hacer varios reclamos en el mismo mensaje?", "Mejor hacerlo de a uno, así cada reclamo queda bien registrado con su propia dirección."),
    ("¿Cuál es el horario de atención telefónica?", "Atendemos por teléfono en el mismo horario que la oficina: de 8 a 14, de lunes a viernes."),
    ("¿Necesito turno para hacer un reclamo?", "No, los reclamos los puede hacer en cualquier momento, sin turno previo."),
    ("¿El organismo tiene oficina en Villa Devoto?", "Sí, hay una dependencia en Villa Devoto. ¿Quiere que le pase la dirección?"),
    ("¿Qué necesito para tramitar la licencia por primera vez?", "Necesita el DNI, el certificado de aptitud psicofísica y aprobar el examen teórico y práctico."),
    ("¿Puedo sacar turno para otra persona?", "Sí, pero la persona interesada tiene que estar presente el día del turno con su documentación."),
    ("¿Puedo hacer la denuncia de un semáforo roto por WhatsApp?", "Sí, puede reportarlo por este mismo medio, indicando la dirección exacta."),
    ("¿Los reclamos tienen un número de seguimiento?", "Sí, cada reclamo queda con un número de referencia para que pueda consultarlo después."),
    ("¿Qué pasa si el reclamo no se resuelve en el plazo estimado?", "Puede volver a consultarnos el estado y, si corresponde, se deriva a un supervisor."),
    ("¿Dónde pago las multas de tránsito?", "Puede pagarlas online en la página del organismo o en las sucursales habilitadas."),
    ("¿Qué documentación lleva el trámite de habilitación de un kiosco?", "Necesita el certificado de uso conforme, el DNI del titular y el contrato de alquiler o título de propiedad."),
    ("¿Los menores pueden hacer un reclamo?", "El reclamo lo tiene que iniciar un adulto responsable."),
    ("¿Puedo consultar el estado de un trámite de otra persona?", "Solo puede consultar trámites a su nombre, salvo que tenga una autorización."),
    ("¿Qué pasa si me equivoco de dirección en un reclamo?", "Puede avisarme y lo corrijo antes de que se asigne a un operador."),
    ("¿Hay línea de WhatsApp para emergencias?", "Para emergencias reales conviene llamar al 911; este canal es para gestiones no urgentes."),
    ("¿Puedo adjuntar una foto a mi reclamo?", "Por este canal todavía no se pueden adjuntar fotos, pero puede describir el problema con el mayor detalle posible."),
    ("¿El trámite de habilitación tiene costo?", "Sí, tiene un costo que depende del rubro y la superficie del local."),
    ("¿Cuánto dura la vigencia de la licencia de conducir?", "Depende de la edad del titular, pero suele ser de 1 a 5 años."),
]


def generar_consultas_informativas():
    return [
        EjemploEntrenamiento(
            instruccion=pregunta,
            intencion="consulta",
            confianza=round(random.uniform(0.78, 0.9), 2),
            llamada_herramienta=None,
            respuesta=respuesta,
            fuente="manual_generado",
        )
        for pregunta, respuesta in CONSULTAS_INFORMATIVAS
    ]


TRAMITES_SIN_TOOL = [
    "Necesito dar de baja un comercio que ya cerró",
    "Quiero presentar la documentación para una exención de la tasa municipal",
    "Necesito cambiar la titularidad de un terreno",
    "Quiero iniciar el trámite de habilitación de un local comercial",
    "Necesito anotar un cambio de domicilio fiscal",
    "Necesito la baja de una partida inmobiliaria",
    "Quiero tramitar una condonación de deuda",
    "Necesito un certificado de libre deuda",
    "Quiero inscribir una nueva actividad comercial",
    "Necesito dar de baja un vehículo que vendí",
    "Quiero pedir una prórroga para pagar una multa",
    "Necesito presentar un descargo por una infracción",
    "Quiero saber cómo transferir la titularidad de un comercio",
    "Necesito hacer el cambio de razón social de mi negocio",
    "Quiero dar de alta un nuevo domicilio comercial",
    "Necesito tramitar el cambio de uso de un local",
    "Quiero pedir la devolución de una tasa mal cobrada",
    "Necesito el alta de un nuevo apoderado para mi comercio",
    "Quiero presentar una nota pidiendo una prórroga de obra",
    "Necesito renovar la habilitación de mi comercio",
    "Quiero dar de baja una partida de alumbrado",
    "Necesito el certificado de aptitud ambiental para mi local",
    "Quiero iniciar un sumario por una infracción que no cometí",
]

RESPUESTAS_TRAMITE = [
    "La gestión que me pide la va a procesar un agente del organismo. Ya derivé su caso, en breve lo van a contactar.",
    "Un agente del organismo va a revisar su trámite. Ya quedó derivado.",
    "Ese trámite lo atiende un agente del organismo. Ya derivé su caso.",
]


def generar_tramites():
    ejemplos = [
        EjemploEntrenamiento(
            instruccion=texto,
            intencion="tramite",
            confianza=round(random.uniform(0.78, 0.9), 2),
            llamada_herramienta=None,
            respuesta=random.choice(RESPUESTAS_TRAMITE),
            fuente="manual_generado",
        )
        for texto in TRAMITES_SIN_TOOL
    ]
    vagos = [
        "Necesito hacer un trámite pero no sé por dónde empezar",
        "Quiero hacer un trámite municipal",
        "Tengo que hacer una gestión en el organismo, ¿me ayudan?",
    ]
    for texto in vagos:
        ejemplos.append(
            EjemploEntrenamiento(
                instruccion=texto,
                intencion="tramite",
                confianza=0.6,
                llamada_herramienta=None,
                respuesta="Cuénteme qué trámite necesita hacer, así derivo su caso al área correspondiente.",
                fuente="manual_generado",
            )
        )
    return ejemplos


OTRO_TEXTOS = [
    "Jaja buenísimo, contame un chiste",
    "Hola, ¿cómo estás?",
    "Pone un poco de música por favor",
    "asdkjh asdkj",
    "Vi un perro perdido en la plaza, ¿alguien sabe de quién es?",
    "Buenas, ¿qué tal el día?",
    "jajaja buenisimo",
    "Contame algo gracioso",
    "Dale que si",
    "ok gracias",
    "asd",
    "Hola buenas tardes como estas todo bien",
    "¿Vos sos una persona o un robot?",
    "Buen día, lindo el clima hoy",
    "Jajaja no entendí nada",
    "Buenas, ¿se puede hablar con un humano?",
    "Qué tal, todo bien?",
    "Nada, era por las dudas",
    "Jajaja no te creo",
    "Hola hola",
    "Me aburrí, chau",
    "Esto es un chatbot?",
    "Dale, nos vemos",
]

RESPUESTAS_OTRO = [
    "Disculpe, no entendí bien su consulta. ¿Se trata de un reclamo, una consulta o un trámite?",
    "Disculpe, no entendí bien su mensaje. ¿Me puede contar de qué se trata?",
    "Disculpe, no logré entender bien el mensaje. ¿Me puede explicar de qué se trata?",
]


def generar_otro():
    return [
        EjemploEntrenamiento(
            instruccion=texto,
            intencion="otro",
            confianza=round(random.uniform(0.3, 0.6), 2),
            llamada_herramienta=None,
            respuesta=random.choice(RESPUESTAS_OTRO),
            fuente="manual_generado",
        )
        for texto in OTRO_TEXTOS
    ]


def main() -> None:
    ejemplos: list[EjemploEntrenamiento] = []
    ejemplos += generar_reclamos_con_direccion(PROBLEMAS_INFRA, "infraestructura", 6)
    ejemplos += generar_reclamos_con_direccion(PROBLEMAS_SERVICIO, "servicio", 7)
    ejemplos += generar_reclamos_incompletos(PROBLEMAS_INFRA, 2)
    ejemplos += generar_reclamos_incompletos(PROBLEMAS_SERVICIO, 2)
    ejemplos += generar_reclamos_tramite()
    ejemplos += generar_reservas_completas(14)
    ejemplos += generar_reservas_incompletas(5)
    ejemplos += generar_reservas_vagas()
    ejemplos += generar_consultar_estado()
    ejemplos += generar_consultas_informativas()
    ejemplos += generar_tramites()
    ejemplos += generar_otro()

    vistos: set[str] = set()
    sin_duplicados: list[EjemploEntrenamiento] = []
    for e in ejemplos:
        if e.instruccion in vistos:
            continue
        vistos.add(e.instruccion)
        sin_duplicados.append(e)

    with open(SALIDA, "w", encoding="utf-8") as f:
        for e in sin_duplicados:
            f.write(e.model_dump_json() + "\n")

    descartados_por_duplicado = len(ejemplos) - len(sin_duplicados)
    con_tool = sum(1 for e in sin_duplicados if e.llamada_herramienta is not None)
    print(f"Generados: {len(ejemplos)}, duplicados descartados: {descartados_por_duplicado}")
    print(f"Total final: {len(sin_duplicados)} -> {SALIDA}")
    print(f"Con llamada_herramienta: {con_tool}")
    import collections
    conteo = collections.Counter(e.intencion for e in sin_duplicados)
    for cat, n in sorted(conteo.items()):
        print(f"  {cat:10s} {n:4d}")


if __name__ == "__main__":
    main()
