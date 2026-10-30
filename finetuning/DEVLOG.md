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

- [x] Correr el notebook en Colab y registrar los resultados reales de los
      tres indicadores — hecho el 2026-10-19, ver entrada más abajo
      ("Entrenamiento completo, export a GGUF y primera medición real").
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

---

## 2026-10-19 — Se perdió un entrenamiento completo por no usar Drive

Se corrió el entrenamiento del notebook de Colab durante la noche. Terminó las
3 épocas, pero la sesión de Colab se desconectó antes de que alguien volviera a
mirarla (por inactividad o por el límite de la cuenta gratis) y no había nada
guardado en un lugar persistente: los checkpoints (`output_dir="outputs"`) y
el export final (`save_pretrained_gguf`) escribían al disco efímero de la VM
(`/content`), que se borra con la sesión. Resultado: 3 épocas de entrenamiento
real, cero artefactos recuperables.

Arreglo aplicado a `finetuning_qwen_colab.ipynb`: nueva celda (sección 1.5) que
monta Google Drive al principio, antes de instalar nada; `output_dir` del
`Trainer` y las llamadas de `save_pretrained`/`save_pretrained_gguf` ahora
escriben dentro de `/content/drive/MyDrive/omnicivitas-finetune/` en vez de
`/content`. Con esto, un corte de sesión a mitad de entrenamiento todavía
pierde el progreso desde el último checkpoint de época, pero no el
entrenamiento completo.

Pendiente: volver a correr el entrenamiento completo desde cero (esta vez con
Drive montado) y recién ahí correr la celda de evaluación sobre
`prueba_tool_calling.jsonl` — los tres indicadores de la tesis siguen sin una
medición real.

---

## 2026-10-19 — Entrenamiento completo, export a GGUF y primera medición real

Se volvió a correr el entrenamiento desde cero (con Drive montado, ver entrada
anterior) y esta vez terminó sin perder nada: las 3 épocas, el
`save_pretrained` y el `save_pretrained_gguf` (exportación para Ollama)
quedaron escritos en Drive. Tardó cerca de 6 horas de principio a fin en la
GPU gratuita de Colab.

### Primera medición real de los tres indicadores

Con el modelo ya exportado a GGUF, se corrió por primera vez la celda de
evaluación sobre las 67 instrucciones de `prueba_tool_calling.jsonl` (el
conjunto de prueba, disjunto de entrenamiento/validación):

| Indicador | Resultado |
|---|---|
| Exactitud de intención | 100% (67/67) |
| Falsos positivos (confianza ≥ 0,6, categoría incorrecta) | 0 |
| Confiabilidad de tool calling (herramienta Y parámetros exactos) | 92,5% (62/67) |

El modelo evaluado es el mismo estado que terminó exportado a `.gguf`, no un
punto intermedio anterior a la conversión: el número de tool calling es
representativo de lo que efectivamente va a correr vía Ollama, no de una
versión previa del modelo.

### Los 5 fallos de tool calling, revisados caso por caso

El script de evaluación compara la llamada a herramienta predicha contra la
esperada con `==` sobre el diccionario completo, incluyendo campos de texto
libre (`descripcion`, `referencia`). Al revisar el detalle de los 5 fallos
(reconstruido a mano, porque el script original no guardaba el `pred` de cada
ejemplo, sólo si había coincidido), aparecieron dos grupos bien distintos:

**3 de los 5 no son fallas reales, son un defecto de la métrica.** En los tres
casos la herramienta y los parámetros estructurados (`categoria`, el nombre
de la tool) coinciden exactamente; lo único que difiere es la redacción de un
campo de texto libre, una paráfrasis válida de lo mismo:

- *"Hace tres días que no pasa el camión de la basura..."* → esperado
  `"No pasa el camión de recolección de basura desde hace tres días en
  Belgrano al 500"`, predicho `"Camión de recolección de basura sin pasar por
  la cuadra en Belgrano al 500"`. Misma tool, misma categoría.
- *"¿Cómo sigue el reclamo que hice la semana pasada?"* → `referencia`
  esperada `"reclamo semana pasada"`, predicha `"reclamo pasado"`.
- *"¿Me puede decir cómo sigue el reclamo del semáforo?"* → `referencia`
  esperada `"el reclamo del semáforo"`, predicha `"semáforo"`.

Comparar estos campos con igualdad exacta de string penaliza al modelo por
decir lo mismo con otras palabras. El 92,5% medido es un piso pesimista: la
exactitud real sobre herramienta + parámetros estructurados es más alta.
Queda pendiente corregir el script para no exigir coincidencia exacta en
campos de texto libre (comparar sólo `nombre` + parámetros no-textuales, o
una métrica de similitud para los textuales) antes de citar el número en la
tesis.

**Los otros 2 quedaron sin diagnóstico confiable, y vale la pena dejarlo
documentado en vez de inventar una explicación:**

- *"¿Cómo viene mi trámite?"* (esperado: `consultar_estado_caso` con
  `referencia: ""`) y *"La plaza San Martín está llena de pozos..."*
  (esperado: `crear_reclamo`, categoría `infraestructura`) contaron como
  fallo en la corrida de los 67 con JSON válido en ambos casos
  (`sin_json_valido: 0` en esa corrida). Al reconstruir el detalle
  regenerando sólo estas dos instrucciones más tarde, la generación devolvió
  texto sin un tool call parseable (`pred = None`) en las dos.
- `generar()` usa `do_sample=False` (greedy, determinístico — `temperature`
  directamente se ignora con `do_sample=False`), así que en principio la
  misma instrucción tendría que generar lo mismo siempre. Que haya dado
  distinto sugiere que el estado de `model` cambió entre la corrida de los 67
  y esta regeneración puntual — la causa más probable es la celda de export a
  GGUF, que corrió *antes* de la evaluación de los 67 pero bien podría haber
  dejado el objeto `model` modificado en memoria de una forma que un
  `generate()` posterior ya no reproduce igual.
- No se confirmó la causa exacta y no corresponde darla por buena sin
  evidencia. Para saberlo de verdad hay que volver a correr el *loop completo*
  de evaluación (no el entrenamiento, que es lo que tarda las 6 horas: sólo
  inferencia sobre 67 ejemplos, unos minutos) guardando `pred` y `crudo` de
  cada ejemplo en `detalle` desde el principio, para no depender nunca más de
  regenerar nada a mano.

### Qué queda para la próxima sesión

- [ ] Corregir el script de evaluación para no penalizar paráfrasis válidas en
      campos de texto libre (`descripcion`, `referencia`) antes de citar el
      92,5% en la tesis.
- [ ] Volver a correr el loop de evaluación completo guardando `pred`/`crudo`
      por ejemplo, para poder diagnosticar cualquier fallo futuro sin
      regenerar nada (y sin el riesgo de hacerlo sobre un `model` que ya
      cambió de estado).
- [ ] Integración en `app/agents/llm.py` para apuntar a Ollama vía el
      endpoint compatible con OpenAI, con el `.gguf` ya exportado (sin
      empezar).

---

## 2026-10-21 — Integración con Ollama: el grafo pasa a usar solo el modelo local

`app/agents/llm.py` deja `ChatAnthropic` y pasa a `ChatOllama` contra
`omnicivitas-qwen`, para los dos roles (intake y ejecutor) y por lo tanto para
todo lo que los usa (resumen, mensajes de escalado, agrupador de reclamos). Se
sacó `langchain-anthropic` de `requirements.txt` y `ANTHROPIC_API_KEY` de la
configuración: no queda ningún LLM comercial, ni como respaldo.

- `ollama/Modelfile`: plantilla ChatML de Qwen2.5 **con soporte de
  herramientas**. La que genera Unsloth junto al GGUF no declara `.Tools`, y
  sin eso Ollama rechaza los pedidos con `bind_tools`.
- `num_ctx` 8192: el entrenamiento usó 1024 (una frase por ejemplo), pero en
  producción entran el prompt del sistema, el historial y los esquemas de las
  herramientas.

### Desajuste a medir: el formato del entrenamiento no es el de la app

El modelo se entrenó para devolver un único JSON (`intencion`, `confianza`,
`llamada_herramienta`, `respuesta`) con un prompt fijo y un solo turno. La app
lo usa en dos llamadas: el intake con salida estructurada
(`ClasificacionIntent`, que además tiene `saludo`, `continua_caso_abierto` y
`requiere_humano`) y el ejecutor con tool calling nativo, hasta cinco
herramientas e historial. El 92,5% medido en Colab no se traslada solo.

`scripts/evaluar_modelo_local.py` mide las dos cosas sobre
`prueba_tool_calling.jsonl`: `--modo entrenamiento` (confirma que el GGUF
servido rinde como en Colab) y `--modo app` (el número que importa). También
reporta tool calling sin comparar campos de texto libre, que era la corrección
pendiente de la métrica. Si el camino de la app rinde claramente peor, la
alternativa es un adaptador que llame al modelo con su prompt de entrenamiento
y traduzca el JSON al estado del grafo.

### Qué queda

- [x] Instalar Ollama, bajar el `.gguf` de Drive y `ollama create` (pasos en
      `ollama/README.md`).
- [x] Correr las dos mediciones y anotar acá los resultados (entrada siguiente).

---

## 2026-10-21 — Mediciones con Ollama, parser propio de herramientas y segunda versión del dataset

### El GGUF servido rinde lo mismo que en Colab

`scripts/evaluar_modelo_local.py --modo entrenamiento`, sobre las 67 de
`prueba_tool_calling.jsonl`, con el modelo servido por Ollama en una RTX 3050
(3,3 s por ejemplo):

| Indicador | Colab | Ollama |
|---|---|---|
| Exactitud de intención | 100% | 100% (67/67) |
| Falsos positivos | 0 | 0 |
| Tool calling exacto | 92,5% | 91,0% (61/67) |
| Tool calling sin campos de texto libre | — | 95,5% (64/67) |

La conversión a GGUF q4_k_m no le hizo perder nada relevante.

### Por el camino de la app: un bug de Ollama y después el desajuste real

La primera medición por el camino de la app dio 43,3% de tool calling. En 26
casos el modelo había generado la llamada correcta y Ollama (0.40.7, runner de
llama.cpp) devolvía la respuesta vacía: con la plantilla Go del `Modelfile` su
parser se traga el texto, y con la plantilla Jinja embebida en el GGUF rechaza
las herramientas ("tools param requires --jinja flag"). Se verificó generando
en crudo (`/api/generate` con `raw`): el texto era una llamada perfecta.

Arreglo: el protocolo de herramientas se resuelve en `app/agents/llm.py`
(`ChatQwenLocal`). Las herramientas se escriben en el prompt del sistema con el
formato exacto de la plantilla de Qwen2.5 y los bloques `<tool_call>` se leen
del texto. Acepta además el JSON del primer fine-tuning y argumentos sueltos
sin envoltorio. Ya no depende de la versión de Ollama.

Con eso, por el camino de la app: intención 100%, falsos positivos 0, tool
calling 65,7% exacto y 76,1% sin texto libre. De los 16 fallos, 10 eran
reclamos que no llamó (sobre todo de categoría `tramite`: pedía una dirección
que ese tipo de reclamo no necesita), 5 eran `servicio` contra
`infraestructura` y 1 una consulta de estado sin referencia.

### Palanca 1: cambios en la app, sin reentrenar

- **Confirmaciones armadas por código** (`app/agents/confirmacion.py`). Después
  de un reclamo o una reserva creados, el ejecutor ya no vuelve a llamar al
  modelo: la confirmación sale de los datos reales de la herramienta. El modelo
  nunca vio un resultado de herramienta en el entrenamiento y en esa segunda
  vuelta inventaba ("ya quedó derivado", "le van a pedir el comprobante").
  Además ahorra una inferencia entera por gestión, que en una llamada se nota.
  `derivar_a_operador` también corta directo al escalado.
- **Criterios de categoría en la descripción de `crear_reclamo`**, los mismos
  con los que se etiquetó el dataset, y la aclaración de que un reclamo de
  `tramite` no necesita dirección.
- **Reglas del prompt alineadas con las del entrenamiento** ("llamá la
  herramienta en ese turno si ya tenés los datos", "nunca inventes un
  parámetro").
- **La fecha de hoy en el prompt del ejecutor.** Sin ella "el jueves a las 10"
  no tiene cómo pasar a AAAA-MM-DD; el dataset tenía el año 2026 fijo. El
  prompt se arma ahora en un solo lugar (`prompt_del_sistema`), que usan el
  nodo, la medición y el dataset.

Resultado: sin mejora en la primera llamada (61,2% exacto y 74,6% sin texto
libre con los criterios y las reglas; 58,2% y 70,1% sumando la fecha y las
descripciones sin sangría). Los fallos se movieron más de lo que bajaron: aparecieron llamadas a
`consultar_estado_caso`, e incluso a un nombre inventado
(`consulta_estado_caso`), ante reclamos nuevos. Con un modelo que no vio este
formato, retocar el prompt reacomoda los errores en vez de eliminarlos. Las
confirmaciones por código sí resuelven el problema que atacan, pero esta
métrica mide solo la primera llamada y no lo refleja.

### Palanca 2: segunda versión del dataset, en el formato de la app

`armar_dataset_app.py` reescribe el dataset como conversaciones idénticas a las
que arma la app. No copia los prompts: importa `SYSTEM_INTAKE`,
`prompt_del_sistema` y `construir_tools` de `app/` y renderiza con
`a_formato_qwen`, la misma función que usa la inferencia. Si un prompt cambia,
el dataset cambia con él.

- **intake** (2024 en train): MASSIVE y MULTI3NLU++ submuestreados a 1600
  repartidos por intención (eran 13 mil y solo enseñan intención), los
  manuales, saludos, pedidos de hablar con una persona y mensajes con
  historial (aportar el dato pedido continúa el caso; un tema nuevo no).
- **ejecutor** (680 en train): los manuales convertidos y lo que el primer
  dataset no tenía. Reclamos y reservas en dos turnos (pide el dato, recién
  después llama), respuestas a partir del resultado de `consultar_estado_caso`
  (un caso, varios, ninguno), `registrar_identidad` (solo, junto con un
  reclamo, o como respuesta al pedido de datos), `derivar_a_operador` para
  trámites y pedidos de una persona, y las elecciones del menú de inicio. Las
  reservas nuevas calculan las fechas desde una fecha de hoy al azar, que va en
  el prompt: el primer dataset tenía días de la semana que no coincidían con el
  calendario ("el lunes 3 de noviembre" de 2026 es martes).
- Las consultas informativas llevan el dato en "Información del organismo",
  como en producción, para no entrenar al modelo a contestar requisitos de
  memoria.
- Las confirmaciones de reclamos y reservas no se entrenan: las arma el código.

Unas 2,6 millones de tokens por época. El notebook
`finetuning_qwen_app_colab.ipynb` entrena 2 épocas en vez de 3 (con 3 se
pasaría del límite de la GPU gratuita) con `MAX_SEQ_LENGTH` 2560, guarda en
carpetas nuevas de Drive (`qwen_omnicivitas_app_*`) y mide tool calling sobre
`app_prueba.jsonl`, el mismo conjunto de prueba con el prompt real.

### Qué queda

- [x] Commit y push (el notebook clona el repo desde GitHub).
- [x] Correr `finetuning_qwen_app_colab.ipynb` en Colab (entrada siguiente).
- [x] Servir el GGUF nuevo con Ollama y medir con
      `scripts/evaluar_modelo_local.py` (entrada siguiente).
- [x] `INSTRUCCION_IDENTIFICACION` (`app/agents/ejecutor.py`) estaba
      definida desde la fase de WhatsApp/email pero ningún código la usaba. Se
      activa: `prompt_del_sistema` la agrega mientras el ciudadano no informó su
      DNI, y el dataset la incluye en las conversaciones de identificación.

---

## 2026-10-22 — Resultados de la segunda versión

El notebook `finetuning_qwen_app_colab.ipynb` entrenó las 2 épocas en unas 2,5
horas (checkpoints 169 y 338) y exportó el GGUF a Drive sin cortes. En Ollama
(0.40.8) quedan los dos modelos: `omnicivitas-qwen` es la v2 y
`omnicivitas-qwen-v1` la primera versión, para poder comparar.

Por el camino de la app, mismos prompts, misma versión de Ollama, mismas 67:

| Modelo | Intención | Falsos positivos | Tool calling exacto | Sin texto libre | s/mensaje |
|---|---|---|---|---|---|
| v1 | 100% | 0 | 59,7% (40/67) | 71,6% (48/67) | 3,7 |
| **v2** | **100%** | **0** | **80,6% (54/67)** | **97,0% (65/67)** | **3,2** |

Los 11 casos entre exacto y sin texto libre tienen herramienta y categoría
correctas: solo cambia la redacción de `descripcion` o `referencia`. Los 2
errores que quedan: "no podaron los árboles y las ramas tapan la luz" sale
`infraestructura` en vez de `servicio` (caso de borde: también habla del
alumbrado) y "la plaza San Martín está llena de pozos" pide calle y altura en
vez de registrar con el nombre de la plaza.

### Conversación real: la identificación no la respetaba el modelo

Corriendo el grafo completo contra la base de desarrollo, la v2 registró el
reclamo de un ciudadano nuevo sin pedirle nombre y DNI, aunque la instrucción
estaba en el prompt. En el dataset, de 55 conversaciones de identificación solo
un tercio enseña a pedir los datos primero, contra unos 200 reclamos completos
que llaman directo a `crear_reclamo`.

Arreglo en código, no en el modelo: mientras el ciudadano no informó su DNI, el
ejecutor no deja correr `crear_reclamo` ni `crear_reserva`. Si el modelo las
pide, se responde con un pedido de datos armado por código
(`confirmacion.pedido_de_identificacion`). El mensaje queda en el caso que abre
el grafo, así que en el turno siguiente, con nombre y DNI, el modelo registra la
identidad y crea el reclamo en el mismo turno (la identidad corre primero
aunque venga después en la respuesta), y la confirmación arranca con
"Gracias, Marta.". Verificado en la conversación real: 3 a 5 s por turno.

### Pautas generales en la base de conocimiento

Los documentos de la base pueden marcarse como pauta general: entran al prompt
del ejecutor en todos los turnos, sin pasar por la búsqueda léxica (como las
skills de comportamiento general de un agente). Ejemplos en `conocimiento/`,
en texto plano porque es lo más barato de leer para el modelo.

Con el grafo completo y el modelo v2, el efecto es limitado. Con las pautas al
final del prompt y la consigna "sin contradecir las reglas anteriores", el
modelo seguía siempre la instrucción de identificación y nunca daba el número
de emergencias. Pasarlas antes del pedido de identificación no alcanzó: el
modelo aprendió a pedir nombre y DNI primero y el dataset no tiene pautas. Se
dejan antes de la identificación igual, porque los controles que importan están
en el código.

La misma corrida destapó algo peor: ante "me mordió un perro", el modelo llamó
a `registrar_identidad` con un "Juan" y un DNI que nadie escribió. Si ese DNI
fuera de otra persona, el contacto se le sumaría y vería sus casos. Arreglo en
código: el DNI solo se registra si aparece, como número, en lo que escribió el
ciudadano (`dni_dicho`).

F5 (identificarse por correo con un DNI existente) salía distinto según la
corrida: el contacto se sumaba bien y no se duplicaba el reclamo, pero el modelo
intentaba registrar el pozo otra vez con una dirección inventada y, bloqueado,
derivaba. Arreglo en código: si el contacto se suma a una persona que ya existe
y el caso pendiente es una consulta, el estado se responde sin el modelo
(`_estado_al_sumar_contacto`, `confirmacion.estado_de_casos`). Para que esa
respuesta diga de qué se trata, `crear_reclamo` deja la descripción como asunto
del caso cuando no tenía uno.

En la misma corrida el modelo escribió "Número de caso: REC-20194FB3" con el
caso real REC-20194FB2. Se quitan de la respuesta las líneas con un número de
caso que no es del ciudadano (`sin_referencias_ajenas`).

### Agenda de turnos: las reglas en el código

La reserva aceptaba cualquier fecha: dos veces el mismo horario, un domingo, el
pasado. Y se guardaba como UTC, así que el turno de las 10 aparecía a las 7. La
agenda pasó a tener grilla (días, horario, minutos por turno, cupos,
anticipación, sede), días bloqueados y estados de reserva; las reglas viven en
`app/db/crud/turnos.py`, con la agenda bloqueada (`FOR UPDATE`) mientras se
reserva y un índice único por ciudadano y horario.

Con el modelo real aparecieron tres fallas, las tres resueltas en el código:

- Inventaba la fecha cuando el ciudadano todavía no la había dicho: sin un día
  nombrado (`dijo_un_dia`) no se reserva y se pregunta.
- Se equivocaba de agenda (pedían licencia y reservaba en el CeSAC): manda la
  agenda que nombró el ciudadano (`agenda_nombrada`), y el día y la hora se leen
  de su mensaje (`app/agents/fechas.py`).
- Confirmaba en el texto reservas que no hizo, con una agenda que no existe:
  si lo que dijo el ciudadano alcanza, se reserva de verdad; si no, se le dice
  que todavía no quedó hecho (`_sin_confirmaciones_inventadas`).

Cancelar y cambiar de horario por chat también se resuelve en el código
(`app/agents/cancelacion.py`): el modelo no tiene esas herramientas y mover el
turno equivocado es peor que no moverlo.

### Tercera versión del dataset

Suma las pautas generales al 40 % de los prompts del ejecutor (en producción un
organismo puede no tenerlas), 60 conversaciones de emergencias (primero el
número de emergencias; después los datos o el reclamo), consultas de violencia
de género (911 y 144), pedidos de opinión política o de claves, y la grilla de
cada agenda en la información de las reservas. El texto que el modelo escribe
junto con una llamada (el aviso de emergencia) ahora se conserva delante de la
confirmación armada por código.

Las conversaciones más largas llegan a unos 2450 tokens (medido con Ollama),
dentro de los 2560 del entrenamiento. El conjunto de prueba se mide sin pautas,
para comparar con la v2.

### Qué queda

- [ ] Si se vuelve a entrenar: más conversaciones de identificación que pidan
      los datos primero, para que el modelo lo haga solo y la regla del código
      quede como red de seguridad.

## 2026-10-28 — Resultados de la tercera versión

El notebook entrenó las 2 épocas y exportó el GGUF a Drive sin cortes (el
armado del dataset falló una vez en Colab porque importaba la conexión a la
base; la lectura de `conocimiento/` pasó a `scripts/archivos_conocimiento.py`,
que no la necesita). En Colab, sobre las 67 de prueba: 94,0% exacto (63/67) y
100% sin campos de texto libre.

En Ollama quedan los tres: `omnicivitas-qwen` es la v3, `omnicivitas-qwen-v2`
y `omnicivitas-qwen-v1`. Por el camino de la app, misma corrida, misma GPU
(RTX 3050):

| Modelo | Intención | Falsos positivos | Tool calling exacto | Sin texto libre | s/mensaje |
|---|---|---|---|---|---|
| v2 | 100% | 0 | 80,6% (54/67) | 97,0% (65/67) | 4,3 |
| **v3** | **100%** | **0** | **77,6% (52/67)** | **98,5% (66/67)** | **4,3** |

La v3 resuelve los dos errores de la v2 (la poda que tapa la luz sale
`servicio`; la plaza llena de pozos se registra con el nombre de la plaza) y
suma uno: "contenedor de reciclaje roto y desbordado" sale `servicio` en vez de
`infraestructura`, un caso de borde porque el contenedor es parte de la
recolección. La baja en exacto es toda de redacción: "reclamo de la semana
pasada" por "reclamo semana pasada", "14 días" por "2 semanas". La v2 tenía las
suyas ("Escombres", "calzada" por "calle").

### Conversación real: las pautas se aplican a medias

Con el modelo real por WhatsApp, el cable caído salió bien (primero el aviso,
después los datos), igual que la pregunta por el intendente y el turno completo
(reservar, cambiar, cancelar). Fallaron tres:

- **Olor a gas**: ningún aviso, y saludó a un "Juan Pérez" que nadie nombró. El
  control de `dni_dicho` frenó el registro con un DNI inventado, pero el texto
  final usaba el nombre.
- **"Mi pareja me está amenazando"**: lo derivó a una persona sin nombrar el
  911 ni el 144.
- **"¿Te paso la clave de Mi Argentina?"**: el intake lo clasificó trámite y se
  derivó; la clave habría llegado a un operador.

Los tres se resolvieron en el código, como el aviso de IA:

- `app/agents/seguridad.py` detecta por palabras la emergencia (violencia,
  persona lastimada, fuego, gas, cable caído, personas atrapadas) y antepone un
  aviso fijo con el número que corresponde, salvo que la respuesta ya lo nombre.
  Se aplica al persistir la respuesta, después del aviso de IA, así que queda
  primero y cubre también las derivaciones y la falla del modelo. Las reglas son
  acotadas a propósito: "es un abuso lo que cobran" no dispara nada.
- Ofrecer una clave o la tarjeta va al ejecutor antes de cualquier otra ruta y
  se contesta con un texto fijo, sin pasar por el modelo ni por un operador.
  "¿Necesito clave fiscal?" es una consulta y no entra.
- `sin_nombre_inventado` (`app/agents/identidad.py`) saca del saludo un nombre
  que no aparece en la conversación: el modelo no tiene otra forma de saberlo.

Repetidas las conversaciones, el gas y la amenaza llegan con el aviso adelante
(el modelo igual deriva, que está bien) y la clave recibe la respuesta fija.

### Continuidad entre canales (F5) con la v3

Con los canales reales andando (WhatsApp por la Cloud API y el correo por
IMAP/SMTP), se repitió el recorrido de F5 con el modelo real: un pozo por
WhatsApp, después "¿cómo va el reclamo del pozo?" por correo, el DNI y una
pregunta más. Con la v3 se rompió en cuatro lugares, todos resueltos en el
código:

- Al identificarse por WhatsApp, el modelo le agregó al pozo tres calles que
  nadie dijo; el control lo frenó, al reintentar volvió a inventar y derivó.
  Ahora, si un mensaje del ciudadano cuenta lo mismo, el reclamo se registra
  con sus palabras (`descripcion_del_ciudadano`). En otra corrida mandó dos
  `crear_reclamo` del mismo pozo y la confirmación salía dos veces: se toma el
  primero.
- Por correo, sin identificar, buscó casos del contacto nuevo y contestó "no
  encontré casos a su nombre". Ahora se le piden los datos para buscarlos.
- El intake clasificó la pregunta como reclamo (por la palabra), y la respuesta
  con el estado solo se daba si el caso era una consulta. Ahora alcanza con que
  se le hayan pedido los datos para buscar sus casos, o con que la pregunta
  pendiente sea por el estado; el caso pasa a ser una consulta.
- Ya identificada, ante "¿para cuándo lo arreglan?" volvió a pedirle nombre y
  DNI, copiando el pedido del historial. Se le corrige una vez y, si insiste,
  va un texto fijo.

Repetido, el recorrido sale entero: pide los datos, registra el reclamo, por
correo pide los datos para buscar el caso, suma el correo y da el estado del
reclamo del pozo. La última respuesta no trae el plazo del bacheo: "arreglan" no
está en el documento de baches y la búsqueda léxica no lo encuentra.

### Qué queda

- [ ] El mensaje con una clave igual queda guardado en las interacciones del
      caso: falta enmascararla antes de persistir.
- [ ] Si se vuelve a entrenar: más conversaciones de emergencias por gas y de
      violencia, para que el modelo dé el aviso solo y la regla quede como red.
- [ ] Que la búsqueda de conocimiento use también el asunto del caso del que se
      habla ("¿para cuándo lo arreglan?" no nombra el pozo).
