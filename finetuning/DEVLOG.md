# Devlog — Fine-tuning del modelo de lenguaje local

Registro de decisiones y hallazgos del desarrollo del dataset de fine-tuning
de Qwen2.5-3B-Instruct, para integrar más adelante a `chapter04.tex`
("Entrenamiento del modelo de lenguaje") o a un capítulo de resultados. Cada
entrada queda fechada y en prosa para poder copiarse casi tal cual.

---

## 2026-10-18 — Arranque: pipeline de dataset (MASSIVE + ejemplos manuales)

Se empezó por la construcción del dataset de fine-tuning, sin todavía tocar
el entrenamiento en sí (que depende de tener datos y corre en Colab, fuera de
este repo). Código en `finetuning/` dentro de OmniCivitas, con un entorno
Python propio (`finetuning/.venv`), separado del de la aplicación: son
dependencias de preparación de datos (`datasets`, `pandas`, `scikit-learn`),
no del sistema que corre en producción.

### Mirror de MASSIVE

El dataset original, `AmazonScience/massive`, se distribuye con un *loading
script* de la librería `datasets` de Hugging Face. Las versiones recientes de
esa librería (5.x) eliminaron el soporte a scripts por razones de seguridad,
así que `load_dataset("AmazonScience/massive", "es-ES")` falla. Se usa en su
lugar el mirror en formato Parquet `mteb/amazon_massive_intent`, mantenido
para el benchmark MTEB, que trae el mismo texto en español y las mismas 60
intenciones originales (`label_text`), sólo que ya convertido a un formato
que `datasets` 5.x puede leer directamente. Partición `train`: 11.514
ejemplos en español.

### Reetiquetado a las 5 categorías del Proyecto

MASSIVE es un dataset de intenciones para un asistente de propósito general
(alarmas, control de dispositivos IoT, música, clima, noticias...), no de
atención ciudadana. Reetiquetar sus 60 intenciones a las 5 categorías del
Proyecto (consulta, reclamo, reserva, trámite, otro) no puede hacerse por
equivalencia de dominio —no hay "alarma" ni "volumen de audio" en un
organismo público— sino por *patrón de comportamiento*: ¿la persona está
pidiendo información (consulta), agendando algo a futuro (reserva), dando de
alta/baja una gestión propia (trámite), o ninguna de las anteriores (otro)?
El mapeo completo, intención por intención, queda en `mapeo_massive.py`, con
una confianza heurística fija por intención (qué tan inequívoco es asignarla
a esa categoría — no es una medición, es una decisión de quien construye el
dataset, documentada así a propósito para que quede claro en una eventual
auditoría de dónde salen esos números).

**Hallazgo importante: MASSIVE no aporta ningún ejemplo de "reclamo".**
Ninguna de sus 60 intenciones corresponde a una queja o reporte de un
problema — es lógico, nadie le reclama a un asistente de voz doméstico que
"se cayó un árbol en la vereda". Tras procesar las 11.514 filas, la
distribución quedó:

| Categoría | Ejemplos | % |
|---|---|---|
| consulta | 5.472 | 47,5% |
| otro | 3.549 | 30,8% |
| reserva | 1.354 | 11,8% |
| trámite | 1.139 | 9,9% |
| **reclamo** | **0** | **0%** |

Esto tiene una consecuencia directa sobre cómo se reparte el trabajo entre
las fuentes del dataset: la categoría más importante del producto —es la que
le da sentido al nombre "reclamo" en el RF-03— depende por completo del
conjunto manual de ejemplos de tool calling, al menos hasta que se incorporó
MULTI3NLU++ más abajo en esta misma sesión.

### Qué sí y qué no enseña cada fuente

El formato de un ejemplo de entrenamiento (`esquema.py`) tiene cuatro campos
además de la instrucción: `intencion`, `confianza`, `llamada_herramienta` y
`respuesta`. Las filas de MASSIVE sólo entrenan los primeros dos
—`llamada_herramienta` y `respuesta` quedan en `null` a propósito—, porque no
tiene sentido fabricar una respuesta de organismo público para una
instrucción de "despertame a las nueve de la mañana": sería un dato
inventado, y entrenar al modelo con respuestas inventadas para instrucciones
reales (aunque de otro dominio) degrada la calidad de lo que aprende a
responder. MASSIVE funciona como *warm-start* de la clasificación de
intención y confianza; todo lo que tiene que ver con el dominio real
—incluido el único lugar donde aparece "reclamo"— depende del conjunto
manual (`ejemplos_tool_calling.jsonl`, 47 ejemplos a mano, ver abajo).

Esto es una limitación a declarar explícitamente si esta sección se integra
a la tesis: el entrenamiento real de `llamada_herramienta` y `respuesta`
depende en esta primera versión de sólo 47 ejemplos manuales, lo cual es muy
poco para los objetivos de ≥90% de exactitud de clasificación y ≥95% de
confiabilidad de tool calling comprometidos en la tesis. Esta carpeta es un
punto de partida reproducible, no el dataset final.

### Ejemplos manuales de tool calling

Se escribieron 47 ejemplos a mano (`ejemplos_tool_calling.jsonl`), fieles a
las tres tools reales que expone `construir_tools` en
`app/agents/ejecutor.py` (`crear_reclamo`, `crear_reserva`,
`consultar_estado_caso`) — mismos nombres de parámetro, mismos valores
válidos (`categoria` de reclamo: `servicio`/`infraestructura`/`tramite`;
`fecha_hora` en formato `AAAA-MM-DD HH:MM`; `turno` como texto libre que debe
calzar con una agenda existente). Ningún ejemplo incluye `caso_id` ni
`ciudadano_id` como parámetro de la llamada a herramienta, porque esas tools
no los reciben del LLM — las cierra el ejecutor por clausura sobre el estado
de la conversación. Esto no es una convención de estilo del dataset: es el
mismo control de seguridad de la Restricción Crítica 2b del proyecto (nunca
confiar en un identificador que el LLM proponga), aplicado en el dataset de
entrenamiento igual que en el código.

Se cubrieron a propósito los dos casos de cada tool: con todos los datos
necesarios (`llamada_herramienta` completa) y con datos faltantes
(`llamada_herramienta: null`, `respuesta` repreguntando lo que falta) — es el
mismo comportamiento que ya implementan `crear_reclamo`/`crear_reserva` en
`graph.py` cuando el ciudadano arranca sin toda la información. También se
incluyó la distinción, documentada en el estado del proyecto, entre "reserva"
(hay agenda y tool: DNI, licencia de conducir, CeSAC) y "trámite" (sin tool
todavía, siempre escala) — son categorías que se pueden confundir si no se
las separa con ejemplos explícitos, porque ambas son "gestiones
administrativas" en lenguaje coloquial.

Distribución de los 47 ejemplos manuales: reclamo 10, reserva 9, trámite 8,
consulta 15 (10 informativas + 5 con `consultar_estado_caso`), otro 5. De
esos 47, 16 tienen `llamada_herramienta` no nula.

### Cómo se separan los splits

La tesis pide un held-out de prueba "armado solo con ejemplos de tool
calling", que no participe ni del entrenamiento ni de la validación. Eso
exige separar dos poblaciones distintas antes de dividir:

1. **Pool general** (todo MASSIVE + MULTI3NLU++ + los ejemplos manuales sin
   tool calling): se divide 90/10 estratificado por `intencion` en
   train/validación. Nunca aporta al conjunto de prueba.
2. **Pool de tool calling** (los 16 ejemplos manuales con
   `llamada_herramienta`): se divide 60/20/20 estratificado por el nombre de
   la herramienta, para que el 20% de prueba sea disjunto del 60%+20% de
   train/validación.

`train.jsonl` y `validacion.jsonl` son la unión de la parte que les toca de
cada pool; `prueba_tool_calling.jsonl` sale sólo del segundo pool.

Con apenas 16 ejemplos de tool calling en total, el 20% de prueba son 4
ejemplos — insuficiente para medir con algo de rigor estadístico el ≥95% de
confiabilidad de tool calling que compromete la tesis (un held-out de 4
ejemplos no distingue 95% de 75% de confiabilidad real). El mecanismo de
split ya queda armado y es correcto; lo que falta es volumen en el conjunto
manual antes de que ese número sea algo más que un placeholder.

### MULTI3NLU++: localización y estructura real

El paper (Moghe et al., Findings of ACL 2023) no da un enlace directo al
dataset; se lo encontró buscando por nombre en Hugging Face Hub:
`uoe-nlp/multi3-nlu` (University of Edinburgh, coincide con los autores). No
es cargable con `datasets.load_dataset` — son archivos JSON sueltos por
idioma/dominio/fold, descargados con `huggingface_hub.hf_hub_download`
(`preparar_multi3nlu.py`).

Tres cosas de la estructura real que no eran obvias desde el paper ni el
dataset card:

1. **Los "folds" (20 por dominio) no son splits de evaluación**: son una
   partición simple y disjunta del dataset completo (se verificó que cada
   `uid` aparece exactamente una vez entre los 20 folds de un dominio). El
   paper los usa para sus propios experimentos de few-shot (Sección 4), pero
   para este proyecto alcanza con unir los 20 archivos de cada dominio.
2. **362 de los 3.080 ejemplos en español no tienen campo `intents`**, sólo
   `slots` — son turnos que completan un dato de una pregunta anterior (ej.
   "llegaremos mañana a las 6:35 de la tarde" respondiendo cuándo llega el
   ciudadano) y no tienen intención propia sin el contexto completo del
   diálogo. Se descartan del reetiquetado.
3. **Es multi-etiqueta, no una intención por frase como MASSIVE**: cada
   frase trae un conjunto de hasta 4-5 etiquetas de un vocabulario de 62,
   que combinan un tipo de acción (`request_info`, `booking`,
   `cancel_close_leave_freeze`...), una entidad de dominio (`card`,
   `appointment`...) y a veces una palabra de pregunta (`how_much`,
   `when`...). No hay mapeo 1 a 1 posible.

### Reetiquetado por regla de prioridad

En `mapeo_multi3nlu.py`, la función `clasificar()` evalúa reglas de arriba
hacia abajo sobre el conjunto de etiquetas de cada frase; gana la primera que
matchea (reclamo > reserva > trámite > consulta > otro, a grandes rasgos).

**Hallazgo: MULTI3NLU++ sí tiene señal de "reclamo"**, a diferencia de
MASSIVE — la etiqueta `wrong_notworking_notshowing` ("algo no funciona/no
aparece", 341 apariciones en las 3.080 frases en español) y `lost_stolen`
("perdido/robado", 82 apariciones) son quejas e incidentes reales. Eso
resuelve el vacío de "reclamo" que dejaba MASSIVE.

**Dos bugs encontrados por inspección manual de muestras aleatorias y
corregidos antes de dejar el dataset por escrito** (la regla inicial
priorizaba la acción por encima de si la frase era, en el fondo, una
pregunta):

- `make_open_apply_setup_get_activate` (alta/activar algo) sin ninguna
  entidad reconocida caía en "trámite" por descarte. Encontrado con "¿cuánto
  pagaría de más al cambiar libras a euros en Italia?" (`how_much` +
  `fees_interests` + `international` + `make_open_apply_setup_get_activate`),
  una consulta de precio, no una gestión a ejecutar. Arreglo: si la frase
  también trae una palabra de pregunta inequívoca (`request_info`,
  `how_much`, `why`, `how`, `how_long`, `when`), gana "consulta".
- `transfer_payment_deposit` (pagar/transferir, la 2da etiqueta más
  frecuente del dataset con 513 apariciones) no tenía ninguna regla propia y
  cayó en el mismo problema: "¿cuándo vence mi próximo débito directo al
  restaurante?" y "¿cuál es el límite mensual de los depósitos...?" (ambas
  con `when`/`how_much` pero sin `request_info`) se etiquetaban "trámite"
  siendo preguntas claras. Mismo arreglo que el punto anterior.

En el camino se notó que `more_higher_after` y `less_lower_before`
(más/menos, antes/después) no son palabras de pregunta confiables: aparecen
igual de seguido en una restricción sobre una acción ("necesito hacer esa
transferencia antes del 4 de noviembre") que en una pregunta comparativa. Se
las separó en `MODIFICADORES_DEBILES`, que sólo suman a favor de "consulta"
como último recurso, nunca para desambiguar una acción.

**Limitación de origen que no se puede corregir con una regla** (encontrada
también por inspección manual, no corregida porque el problema está en la
etiqueta original del dataset, no en el mapeo): `wrong_notworking_notshowing`
combina en una sola etiqueta "está roto/anda mal" (queja real) con "no
aparece/no muestra" (que puede ser una afirmación neutra, ej. "no tengo nada
pendiente" se etiquetó "reclamo" por esta razón, sin ser una queja). Se
revisaron a mano las 423 frases por esta razón — ver más abajo, "Revisión
manual de los 423 'reclamo'".

Distribución final tras los dos arreglos, sobre 2.718 ejemplos (de 3.080,
descontados los 362 sin `intents`):

| Categoría | Ejemplos | % |
|---|---|---|
| consulta | 836 | 30,8% |
| otro | 608 | 22,4% |
| **reclamo** | **423** | **15,6%** |
| reserva | 353 | 13,0% |
| trámite | 498 | 18,3% |

Igual que con MASSIVE, estas filas sólo entrenan `intencion` + `confianza`
(`llamada_herramienta` y `respuesta` quedan en `null`): el contenido sigue
siendo de dominios bancario/hotelero, no de atención ciudadana, y fabricar
una respuesta de organismo público para "quiero bloquear mi tarjeta" sería
igual de falso que hacerlo para una frase de MASSIVE.

Con esto, el pool general (sin tool calling) queda en 14.263 ejemplos
(11.514 de MASSIVE + 2.718 de MULTI3NLU++ + 31 manuales sin tool), y
`armar_dataset.py` ya corre de punta a punta sobre las tres fuentes:
`train.jsonl` 12.845, `validacion.jsonl` 1.430, `prueba_tool_calling.jsonl` 4
(sigue siendo sólo del conjunto manual — ver limitación de volumen más
arriba, no cambió con esto).

### Ejemplos generados por plantilla

El cuello de botella señalado arriba —16 ejemplos de tool calling, 4 en el
held-out de prueba— se atacó en la misma sesión: `generar_ejemplos.py`
combina plantillas de frase con bancos de variación (30 barrios de CABA, 26
calles, ~12 descripciones de problemas de infraestructura, 5 de servicio, 5
de trámite-reclamo, 12 combinaciones de fecha/hora, bancos de consultas
frecuentes y de frases de trámite/otro) para generar un volumen mucho mayor
sin escribir cada frase a mano.

Importante: estos 220 ejemplos (`ejemplos_generados.jsonl`) se guardan con
`fuente="manual_generado"`, distinto de `fuente="manual"` de los 47
originales. La razón es honestidad sobre el proceso: los 47 los escribí y
revisé uno por uno; estos salen de combinar plantillas y sólo se revisó una
muestra aleatoria (no cada uno individualmente). Si esta sección se integra
a la tesis, esa distinción de procedencia tiene que quedar explícita — no es
lo mismo "cada ejemplo fue escrito a mano" que "se generaron por plantilla y
se auditó una muestra".

Los datos (calles, barrios, montos, números de caso) son todos ficticios,
igual que el resto de los datos de demo del proyecto (`scripts/seed_demo.py`).

Se revisó a mano una muestra aleatoria de 15 ejemplos generados — sin
encontrar errores de formato de tool calling ni frases forzadas— antes de
integrarlos a `armar_dataset.py`.

Resultado: el pool de tool calling pasó de 16 a **139** ejemplos (123
generados + 16 manuales), y el held-out de prueba de **4 a 28**
(`consultar_estado_caso`: 6, `crear_reserva`: 6, `crear_reclamo`: 16). Sigue
sin ser un número que sostenga por sí solo el ≥95% de confiabilidad
comprometido en la tesis —para eso haría falta un orden de magnitud más—,
pero ya es una base muchísimo más razonable que los 4 anteriores, y el
mecanismo para seguir creciendo (agregar más bancos de variación o más
plantillas) queda armado y documentado.

Distribución final del pool general (sin tool calling), sumando las cuatro
fuentes: 14.360 ejemplos. `train.jsonl` 13.007, `validacion.jsonl` 1.464,
`prueba_tool_calling.jsonl` 28.

### Revisión manual de los 423 "reclamo"

Se leyeron las 423 frases en español completas (341 de
`wrong_notworking_notshowing` + 82 de `lost_stolen`, sin solapamiento entre
ambas), no una muestra — es poco volumen para revisar entera y es la
categoría más sensible del dataset. Conclusión general: la gran mayoría son
quejas genuinas y bien etiquetadas (tarjetas rechazadas, pagos revertidos,
wifi/aire acondicionado rotos, objetos perdidos/robados) — el tag no está
mal pensado, pero mezcla dos cosas distintas bajo el mismo nombre y eso
produce un número chico de falsos positivos reales.

Se encontraron y excluyeron **14 frases** (15 filas, una se repite) que caen
en dos patrones concretos, ninguno de los dos una queja:

1. **Niegan el problema en vez de reportarlo**: "No, no fue revertido",
   "no, esa es la hora correcta", "No, no se ha perdido", "No, no lo
   olvidé.", "no tengo nada pendiente" — la etiqueta dispara igual aunque el
   texto diga literalmente lo contrario de "algo anda mal".
2. **Corrección de un dato de identidad durante una verificación**: "la
   fecha de nacimiento no es correcta, es el 5 de mayo de 1962", "No, este
   no es el nombre correcto del beneficiario." — corrigen un dato que tomó
   mal el sistema (o el agente humano del otro lado), no se están quejando
   de que algo esté roto.

No hay ninguna combinación de etiquetas que distinga estos casos de los
+400 que sí son quejas reales — "deny" aparece tanto en negaciones del
problema como en quejas reales ("No, no fue revertido" vs. "No, no está en
la lista", esta última sí se deja como reclamo porque reporta algo
ausente). Por eso la exclusión quedó como lista de texto exacto
(`EXCLUSIONES_REVISADAS_A_MANO` en `mapeo_multi3nlu.py`), no como una regla
más — es, literalmente, lo que significa "revisado a mano": no generaliza
a frases nuevas que no se leyeron.

Quedó una frase borderline que se decidió **mantener** a propósito, para que
el criterio de inclusión/exclusión quede trazable: "No, no está en la
lista" — a diferencia de "No, no fue revertido" (niega que haya pasado algo
malo), esta reporta que algo que debería estar ahí no aparece, que sigue
siendo el patrón de queja real del tag.

Con la exclusión, "reclamo" de MULTI3NLU++ pasó de 423 a **408** ejemplos
(15 descartados). Distribución final de todo MULTI3NLU++ sobre 2.703
ejemplos: consulta 836 (30,9%), otro 608 (22,5%), **reclamo 408 (15,1%)**,
reserva 353 (13,1%), trámite 498 (18,4%).

### Datasets evaluados y descartados

Antes de seguir ampliando el dataset de intención/tool calling, se evaluaron
tres fuentes adicionales:

- **SUACI** (`data.buenosaires.gob.ar/dataset/sistema-unico-atencion-ciudadana`),
  el sistema real de reclamos del GCBA (equivalente al 311 de otras
  ciudades): tiene categoría, barrio, calle, altura y tipo
  (Reclamo/Solicitud) reales de CABA desde 2014, pero **sin texto libre de
  lo que escribió el vecino** — solo campos categóricos. No sirve como
  fuente de frases, aunque sí podría usarse más adelante para que
  `generar_ejemplos.py` use barrios/calles/categorías reales de CABA en vez
  de inventados, citando la fuente. No se integró esta sesión.
- **Contact center en español** (transcripciones de llamadas de atención al
  cliente): no se encontró ninguna fuente libre utilizable. `AxonData`
  (Hugging Face) es una muestra comercial — solo 1 fila gratis, la base
  completa (1.000+ horas) requiere pago al proveedor, fuera del presupuesto
  del Proyecto. `CALLHOME Spanish` es gratuito pero son llamadas telefónicas
  personales entre conocidos, no de atención al cliente — dominio
  equivocado. Esto importa poco para el LLM en sí: una vez que el audio pasa
  por ASR, el texto que ve Qwen es igual sea de WhatsApp o de una llamada
  transcripta. Donde sí haría falta (robustez a habla transcripta, con
  muletillas y sin puntuación) es Fase 9, última prioridad.
- **`somosnlp/lenguaje-claro-dataset`** (Hugging Face, Apache 2.0, 4.094
  pares, generados con GPT-3.5): textos legal-administrativos de España
  (ministerios, políticas de cookies) con su versión simplificada. Se
  revisó una muestra de 8 pares — la simplificación es de buena calidad
  (oraciones más cortas, menos tecnicismo), pero el **registro no calza**
  con lo que necesita el agente: las respuestas "simples" de este dataset
  siguen siendo párrafos largos con viñetas y negrita markdown, porque
  simplifican *documentos*, no responden una pregunta corta en un chat. Si
  se mezclaran tal cual en el entrenamiento, el riesgo es que el modelo
  aprenda a contestarle al ciudadano con párrafos largos con viñetas en vez
  de una frase corta — exactamente lo contrario de lo que pide el prompt
  del ejecutor ("usted, lenguaje simple y claro"). Se descartó mezclarlo
  como filas de entrenamiento.

En cambio, sí se usó como vara de referencia: se auditaron las 267
`respuesta` de `ejemplos_tool_calling.jsonl` + `ejemplos_generados.jsonl`
contra tres chequeos simples (más de 25 palabras, jerga burocrática típica
— "en virtud de", "de conformidad con", "sírvase" — y formato markdown). Las
267 pasan los tres chequeos sin excepción, así que no hizo falta reescribir
nada; quedó como una verificación, no como un hallazgo que corregir.

### Segunda vuelta de ampliación del generador

Se volvió a `generar_ejemplos.py` para sumar más bancos y subir los
multiplicadores: 9 problemas de infraestructura nuevos (grafitis, rampa de
accesibilidad rota, escombros de obra, árbol seco, etc.), 5 de servicio
(ruido de obra sin horario, caniles rotos, playón sin luz...), 4 de
trámite-reclamo (multa ya pagada, deuda indebida...), 6 fechas más para
reservas, 12 preguntas informativas más, 8 trámites sin tool más y 8 frases
de "otro" más. También se le agregó variedad de `respuesta` a los casos que
antes tenían una sola frase fija (reclamo incompleto, reserva incompleta,
`consultar_estado_caso`) — una sola frase repetida 100+ veces es la clase de
patrón mecánico que un fine-tune memoriza en vez de generalizar.

**Dos bugs encontrados por inspección de una segunda muestra aleatoria**
(los mismos de siempre: generar sin revisar no sirve, hay que revisar lo
generado):

- La plantilla `"Quiero sacar un turno de {turno} el {fecha}"` combinada
  con una fecha que ya empieza con "el" (la mayoría: "el lunes 3 de
  noviembre...") producía *"quiero sacar un turno de licencia de conducir
  el el 30 de noviembre..."* — doble "el". Este bug ya estaba en la primera
  tanda de 220 ejemplos; la primera revisión manual no lo agarró porque la
  muestra aleatoria de esa vez no cayó en esa combinación de plantilla y
  fecha. Se cambió el "el" de la plantilla por "para", que funciona igual
  con cualquier fecha del banco.
- "los caniles para perros **del barrio** están todos rotos" combinado con
  el locador vago "**en mi barrio**" quedaba *"...del barrio están todos
  rotos en mi barrio"*, redundante. Se le sacó "del barrio" a la frase del
  banco, ya que el locador lo agrega.

Con los multiplicadores más altos, **reclamo creció mucho más que reserva y
consulta por tool calling** (más problemas de reclamo en los bancos, y cada
uno se repite más veces) — queda una asimetría a corregir en la próxima
ronda: el held-out de prueba por herramienta quedó en `crear_reclamo`: 50,
`crear_reserva`: 9, `consultar_estado_caso`: 8. Para `crear_reclamo` ya es
un número razonable para medir confiabilidad; para las otras dos sigue
siendo chico — hace falta sumar más fechas/turnos y más plantillas de
`consultar_estado_caso`, no más de reclamo, en la próxima vuelta.

Resultado total: de 220 a **489** ejemplos generados (317 con
`llamada_herramienta`, antes 123). Sumado al set manual (47, 16 con tool),
el pool de tool calling total pasó de 139 a **333**, y el held-out de
prueba de 28 a **67**. Dataset final: pool general 14.420, `train.jsonl`
13.177, `validacion.jsonl` 1.509, `prueba_tool_calling.jsonl` 67.

### Notebook de Colab (Unsloth + QLoRA)

Se escribió `finetuning_qwen_colab.ipynb`, verificando contra los notebooks
oficiales de Unsloth (`unslothai/notebooks` en GitHub, los de Qwen3 y Qwen2.5
Coder) el patrón de API real antes de escribir código — `FastLanguageModel.
from_pretrained`, `get_chat_template("qwen-2.5")`, `get_peft_model`,
`SFTTrainer`/`SFTConfig`, `train_on_responses_only`, `save_pretrained_gguf` —
en vez de confiar en lo que recordaba de memoria, porque la API de Unsloth
cambia seguido entre versiones.

El notebook clona este mismo repo de GitHub y corre `preparar_massive.py`,
`preparar_multi3nlu.py`, `generar_ejemplos.py` y `armar_dataset.py` ahí
adentro para regenerar el dataset, en vez de depender de subir archivos a
mano a Colab — mismo dataset reproducible que en local.

**Conversión del esquema a formato de chat**: cada fila de
`EjemploEntrenamiento` (instrucción + intención + confianza + llamada\_
herramienta + respuesta) se convierte a una conversación de 3 turnos
(system/user/assistant), donde el turno del asistente es el JSON completo
que el modelo tiene que aprender a producir. El prompt de sistema usado para
entrenar es una versión resumida del `SYSTEM_EJECUTOR` real
(`app/agents/ejecutor.py`) — documentado como simplificación a propósito:
producción separa intake (clasifica) de ejecutor (tool calling + responde)
en dos agentes y dos prompts distintos, y ninguno de los dos modela la
identificación del ciudadano (`registrar_identidad`) ni la derivación a
operador (`derivar_a_operador`) porque dependen de estado de conversación
que este dataset de un solo turno no tiene. Ampliar el dataset para cubrir
esos dos casos es trabajo a futuro, no algo que haga este notebook hoy.

Hiperparámetros usados en la celda de LoRA y de entrenamiento: los mismos
que ya estaban comprometidos en `chapter04.tex` antes de escribir una sola
línea de este notebook (rank 16, alpha 32, dropout 0,05, sobre
`q/k/v/o_proj` + `gate/up/down_proj`; LR 2e-4, scheduler coseno, 3 épocas,
batch efectivo 16 con micro-batch 4 × acumulación 4) — no se inventó ningún
valor nuevo acá, sólo se tradujo lo que ya estaba escrito a los argumentos
reales de `SFTConfig`.

La celda de evaluación mide exactamente los tres indicadores que compromete
la tesis sobre `prueba_tool_calling.jsonl`: exactitud de intención,
conteo de falsos positivos (confianza ≥ 0,6 con categoría incorrecta) y
confiabilidad de tool calling (herramienta Y parámetros exactos). No se
corrió todavía — necesita la GPU de Colab, no esta máquina.

### Qué queda para la próxima sesión

- [ ] Correr el notebook en Colab y registrar los resultados reales de los
      tres indicadores — hoy son metas, no mediciones (igual que aclara
      `chapter04.tex`).
- [ ] Ampliar el dataset para cubrir `registrar_identidad` y
      `derivar_a_operador`, o decidir explícitamente dejarlos fuera del
      fine-tuning y resolverlos por código en vez de por el modelo.
- [ ] Rebalancear `generar_ejemplos.py`: sumar más fechas/plantillas de
      `crear_reserva` y más referencias/plantillas de
      `consultar_estado_caso` — reclamo ya tiene volumen de sobra, las
      otras dos tools todavía no.
- [ ] Integración en `app/agents/llm.py` para apuntar a Ollama vía el
      endpoint compatible con OpenAI, con el `.gguf` que exporta este
      notebook (sin empezar).
- [ ] Los datasets de audio (Common Voice Rioplatense, Google Argentinian
      Spanish) que menciona la tesis en esta misma sección no son parte de
      este dataset de texto — son para adaptar faster-whisper/Kokoro al
      acento rioplatense (Fase 9, canal de voz), no para el fine-tuning de
      Qwen. Vale aclarar esa separación si esta sección se integra a la
      tesis tal como está escrita hoy, porque el texto actual de
      `chapter04.tex` los lista junto a MASSIVE y MULTI3NLU++ como si los
      cuatro alimentaran el mismo fine-tuning.
- [ ] Integración en `app/agents/llm.py` para apuntar a Ollama vía endpoint
      compatible con OpenAI (sin empezar).
