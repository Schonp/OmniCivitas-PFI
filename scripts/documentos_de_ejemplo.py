"""Los documentos de ejemplo de la base de conocimiento, sin tocar la base.

Separados de `seed_conocimiento.py` para que el armado del dataset de
fine-tuning los pueda usar en Colab, donde no hay `.env` ni base (mismo motivo
que `archivos_conocimiento.py`). Cómo está redactado el contenido, y por qué,
está en el docstring de `seed_conocimiento.py`.
"""

# (título, contenido). El contenido arranca por el dato duro: si algún día se
# recorta por MAX_CARACTERES_FRAGMENTO, lo primero es lo que sobrevive.
DOCUMENTOS: list[tuple[str, str]] = [
    # --- Reclamos de vía pública -------------------------------------------
    (
        "Alumbrado público: luminarias apagadas o dañadas",
        "Las luminarias apagadas, intermitentes o con el foco quemado se reclaman "
        "indicando la altura exacta y la esquina más cercana. También ingresan por "
        "esta vía los postes de luz inclinados o con cables sueltos a la vista. El "
        "plazo de reparación es de 5 días hábiles. Los casos con riesgo eléctrico, "
        "como un cable caído o un tablero abierto, se atienden dentro de las 24 horas.",
    ),
    (
        "Baches, pozos y hundimientos en la calzada",
        "Los baches, pozos y hundimientos del asfalto se registran con la calle, la "
        "altura y el carril afectado. Un pozo que interrumpa el paso de peatones o "
        "deje hierros expuestos se clasifica como urgente. El bacheo común se ejecuta "
        "dentro de los 10 días hábiles. Las roturas provocadas por obras de empresas "
        "de servicios se derivan a la empresa responsable, que repone el pavimento.",
    ),
    (
        "Recolección de residuos, basura y contenedores",
        "La recolección domiciliaria pasa de lunes a sábado entre las 20 y las 23. Los "
        "reciclables se retiran martes y viernes. Se reclama por contenedor roto, "
        "faltante, desbordado o quemado indicando su ubicación. Los residuos "
        "voluminosos, como muebles y colchones, se retiran con solicitud previa. Las "
        "bolsas de basura se sacan como máximo dos horas antes del horario de paso.",
    ),
    (
        "Poda de árboles y ramas caídas",
        "La poda del arbolado se solicita indicando la dirección y el motivo: ramas "
        "que tocan cables, que tapan una luminaria o que obstruyen la vereda. Un árbol "
        "caído, o inclinado con riesgo de caerse, se atiende como urgencia dentro de "
        "las 24 horas. La poda programada se realiza entre mayo y agosto. La "
        "extracción de un ejemplar sano no se autoriza sin informe técnico previo.",
    ),
    (
        "Ruidos molestos y horarios de descanso",
        "Los ruidos molestos de locales, obras o vecinos se denuncian con la "
        "dirección, el horario y la frecuencia con que ocurren. El descanso nocturno "
        "rige entre las 22 y las 8. Las obras particulares trabajan de lunes a viernes "
        "de 8 a 18 y los sábados de 9 a 13. La inspección se realiza sin aviso previo "
        "y puede terminar en acta de infracción al responsable del ruido.",
    ),
    (
        "Pérdidas de agua, cloacas y desagües tapados",
        "Las pérdidas de agua en la vía pública, las cloacas desbordadas y los "
        "desagües obstruidos se reclaman con la ubicación exacta. Una pérdida que "
        "inunde la calzada o comprometa los cimientos de una vivienda se atiende como "
        "urgencia. Los sumideros pluviales tapados se limpian dentro de las 72 horas. "
        "La falta de presión dentro del domicilio corresponde a la empresa prestataria.",
    ),
    # --- Reservas y turnos --------------------------------------------------
    (
        "Polideportivo: pileta, natatorio y canchas",
        "El natatorio funciona de lunes a viernes de 7 a 21 y los sábados de 9 a 17. "
        "El uso libre de la pileta no requiere reserva en la franja de 12 a 14. Las "
        "clases de natación y el gimnasio se reservan con turno previo y apto médico "
        "vigente, que se renueva cada seis meses. Las canchas de fútbol y de básquet "
        "se reservan con 48 horas de anticipación y un máximo de dos horas por semana.",
    ),
    (
        "Turnos de atención en las sedes comunales",
        "Los turnos en las sedes comunales se otorgan por franja horaria, de lunes a "
        "viernes de 8 a 15. Quien llega sin turno se atiende solo por urgencias o ante "
        "demoras mayores a 30 minutos. Un turno perdido se reprograma sin penalidad "
        "hasta dos veces; a la tercera inasistencia se bloquea la agenda por 30 días. "
        "La cancelación se avisa con 24 horas de anticipación.",
    ),
    # --- Trámites -----------------------------------------------------------
    (
        "Licencia de conducir por primera vez",
        "La licencia inicial exige DNI vigente, certificado de grupo sanguíneo, libre "
        "deuda de infracciones y el curso teórico aprobado. El examen práctico se "
        "rinde con vehículo propio o del organismo. Los menores de 21 años presentan "
        "autorización firmada de ambos progenitores. La primera licencia tiene "
        "vigencia de un año y recién después se renueva por cinco años.",
    ),
    (
        "Habilitación de comercios minoristas",
        "La habilitación de un comercio minorista sin elaboración de alimentos exige "
        "título de propiedad o contrato de locación, plano de superficie, inscripción "
        "en ingresos brutos y certificado de uso conforme. La habilitación "
        "simplificada resuelve en 15 días hábiles los locales de menos de 200 metros "
        "cuadrados. Los rubros con depósito de inflamables llevan inspección previa.",
    ),
    (
        "Partidas y certificados del Registro Civil",
        "Las partidas de nacimiento, matrimonio y defunción se emiten con DNI del "
        "solicitante y los datos del acta: año, tomo y número. Un familiar directo las "
        "solicita sin autorización adicional; el resto necesita poder o autorización "
        "firmada. La partida reciente se entrega en el momento. Las anteriores a 1950 "
        "demoran 10 días hábiles porque se buscan en el archivo histórico.",
    ),
    (
        "Exención de ABL para jubilados y personas con discapacidad",
        "Los jubilados y pensionados con haber mínimo acceden a la exención del ABL si "
        "son titulares de una única propiedad y viven en ella. Se presenta recibo de "
        "haberes, DNI y la última boleta. El beneficio también alcanza a personas con "
        "discapacidad certificada. La exención se renueva todos los años y no cubre la "
        "deuda anterior a la fecha de solicitud.",
    ),
    # --- Consultas generales -------------------------------------------------
    (
        "Sedes, horarios y canales de atención al vecino",
        "La atención presencial funciona de lunes a viernes de 8 a 15 en las sedes "
        "comunales. La mesa de entradas recibe documentación hasta las 14. Los canales "
        "de WhatsApp y correo electrónico operan las 24 horas: la respuesta automática "
        "es inmediata y la derivación a un agente ocurre en horario administrativo. "
        "Las urgencias de vía pública se reciben en cualquier momento del día.",
    ),
    (
        "Seguimiento de un reclamo o expediente",
        "Cada reclamo recibe un número de referencia que empieza con REC y se informa "
        "al registrarlo. El estado se consulta con ese número desde cualquiera de los "
        "canales, sin repetir los datos personales. Los expedientes de habilitaciones "
        "y licencias usan el prefijo TRA, y las consultas el prefijo CON. Un reclamo "
        "sin movimiento durante 30 días se cierra y admite reapertura.",
    ),
]
