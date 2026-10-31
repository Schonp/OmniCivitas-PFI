# Devlog — Canal de voz (Fase 9), ASR/TTS

Registro de decisiones y hallazgos del desarrollo del servicio de ASR/TTS.
Mismo criterio que `finetuning/DEVLOG.md`: prosa fechada, pensada para poder
integrarse a la tesis o a un informe de avance sin reescribir de cero.

---

## 2026-10-19 — Arranque: servicio de ASR/TTS separado del proceso de la API

Antes de escribir código se resolvió una decisión de arquitectura: ¿faster-
whisper y Kokoro corren adentro del proceso de FastAPI, o aparte? Se eligió
**aparte**, mismo patrón que ya usa el LLM (corre vía Ollama, no cargado en
el proceso de la API) — así los tres servicios de IA quedan simétricos, y el
servidor de la API no pasa a cargar modelos de ML pesados en el mismo proceso
que atiende requests HTTP. Queda como `voz_asr_tts/`, con su propio entorno
Python y `requirements.txt`, mismo criterio que `finetuning/`.

### Dos bugs de entorno encontrados y resueltos antes de poder probar nada

1. **Kokoro necesita `espeak-ng` instalado a nivel de sistema** (no es un
   paquete de Python) para el fallback de pronunciación. No estaba en esta
   máquina. Se intentó instalar con Chocolatey (`choco install espeak-ng`),
   pero el feed de Chocolatey devolvió error 499 (problema del servicio, no
   del paquete). Se resolvió con `winget install eSpeak-NG.eSpeak-NG`
   (Windows 11 ya trae winget) — instaló 1.52.0 sin problema. Para la
   infraestructura real (Linux) esto es simplemente `apt-get install
   espeak-ng`, sin esta complicación.

2. **`faster-whisper==1.2.1` no transcribe nada**: tira
   `TypeError: open() got an unexpected keyword argument 'metadata_errors'`
   al llamar a `transcribe()` con cualquier audio. No es un bug de este
   proyecto — es un incompatibilidad conocida entre faster-whisper 1.2.1 y
   PyAV ≥19 (`SYSTRAN/faster-whisper#1589`): PyAV 19 eliminó el parámetro
   `metadata_errors` que `faster_whisper/audio.py` todavía pasa. faster-
   whisper declara `av>=11` sin techo, así que una instalación nueva hoy
   (octubre 2026) cae en PyAV 19.x y se rompe. Fix: pinear `av==18.1.0`
   (confirmado funcional por varios proyectos que reportaron el mismo bug).
   Quedó documentado con comentario en `requirements.txt` para que no se
   actualice "a ciegas" en el futuro y vuelva a romperse.

### Verificación empírica antes de integrar nada

Se probó un round-trip completo contra los endpoints HTTP reales (no solo las
librerías sueltas): texto → `POST /sintetizar` (Kokoro, voz `ef_dora`) → WAV
→ `POST /transcribir` (faster-whisper, modelo `small`) → mismo texto de
vuelta, español detectado con 100% de confianza. Confirma que el servicio
funciona de punta a punta antes de escribir una sola línea de
`app/channels/voz.py`.

También se confirmó que `WhisperModel.transcribe()` acepta un `BytesIO` en
memoria, no solo una ruta de archivo en disco (la documentación oficial no lo
confirma explícitamente) — importante porque el canal de voz va a recibir
audio en memoria desde el WebSocket de Twilio, no un archivo.

### Hallazgo: Kokoro tiene muy pocas voces en español

Investigado antes de elegir una: Kokoro solo trae **3 voces en español**
(`lang_code='e'`): `ef_dora` (femenina, la única opción), `em_alex` y
`em_santa` (masculinas). Comparado con las decenas de voces en inglés, es una
limitación real del modelo, no una elección de diseño — se eligió `ef_dora`
por ser la única femenina disponible, sin más criterio de selección posible
dentro de este modelo. Si la calidad de esa voz no convence en una prueba con
usuarios reales, la alternativa no es "elegir otra voz en español" (no hay
otra femenina), sino evaluar otro motor de TTS — eso quedaría como una
alternativa evaluada y descartada (o no) en una futura revisión.

### Cambios en la app principal

- `app/core/config.py`: se sacó `whisper_api_key` (sugería un cliente a una
  API externa, inconsistente con la arquitectura de la tesis) y se agregó
  `voz_asr_tts_url` (default `http://localhost:8001`), apuntando a este
  servicio.
- `.env` / `.env.example`: mismo cambio reflejado.

---

## 2026-10-19 (cont.) — `app/channels/voz.py`: webhook + WebSocket de Media Streams

Se armó el canal en sí, siguiendo el patrón de `whatsapp.py` (`CANAL =
Canal.voz`, `identificar_ciudadano`, un punto de entrada que llama a
`procesar_mensaje`). Se verificó primero el protocolo real de Twilio Media
Streams contra la documentación oficial (esquema exacto de los mensajes
`connected`/`start`/`media`/`mark`/`clear`/`stop`, y el TwiML
`<Connect><Stream>` necesario para que el Stream sea bidireccional) en vez de
armarlo de memoria.

### Arquitectura del turno de voz: distinta a WhatsApp/email

WhatsApp y email son canales de petición-respuesta: un webhook por mensaje.
Una llamada es una única conexión larga -- el webhook HTTP de alta
(`POST /api/webhooks/voz`) solo devuelve el TwiML que conecta un WebSocket
(`/api/webhooks/voz/stream`), y toda la conversación corre sobre esa misma
conexión mientras dura la llamada. Por eso acá no hay un `recibir_mensaje`
por request como en WhatsApp: hay un **detector de turno** que acumula audio
y dispara el ciclo completo (ASR → `procesar_mensaje` → TTS) cuando detecta
que el ciudadano terminó de hablar.

### Detección de turno: por qué energía y no VAD

Twilio no hace reconocimiento de actividad de voz (VAD): manda audio continuo
sin importar si el ciudadano habla o calla. `DetectorDeTurno`
(`app/channels/voz.py`) usa un umbral de energía simple (`audioop.rms` sobre
el PCM decodificado de cada chunk mulaw) con dos contadores: cuántos chunks
consecutivos hubo de habla (mínimo antes de considerar que hubo algo real) y
cuántos de silencio sostenido después (umbral de "terminó de hablar"). No es
un VAD real -- no distingue ruido de fondo de una voz baja, y los umbrales
(`UMBRAL_ENERGIA_VOZ`, `CHUNKS_SILENCIO_FIN_TURNO`, `CHUNKS_MINIMOS_HABLA`)
están afinados a ojo, no medidos contra audio real todavía. Es la opción más
simple que podía quedar probada hoy sin una llamada real; un VAD de verdad
(ej. Silero VAD) queda como mejora posterior si la calidad no alcanza.

### Validación de firma de Twilio: por qué sí se usó su SDK

`whatsapp.validar_firma` reimplementa a mano el HMAC-SHA256 de Meta (simple,
bien documentado). Para Twilio se evaluó hacer lo mismo y se descartó: la
documentación oficial de Twilio dice explícitamente *"don't implement your
own signature validation"* -- su algoritmo tiene más matices (orden exacto de
concatenación de parámetros, casos de URL-encoding) que no están
completamente documentados públicamente. Se agregó el paquete `twilio`
(`RequestValidator`) sólo para esto -- es la única pieza de ese SDK que se
usa en todo el proyecto, no se adoptó el SDK completo.

### Conversión de audio: `audioop` en vez de reimplementar G.711

Se evaluó reimplementar el códec mulaw (G.711) a mano con numpy, para no
depender de un módulo stdlib deprecado. Se descartó: `audioop` ya resuelve
decode/encode de mulaw (`ulaw2lin`/`lin2ulaw`), resampleo (`ratecv`, usado
para bajar Kokoro de 24kHz a los 8kHz que espera Twilio) y cálculo de energía
(`rms`, usado por el detector de turno) en una sola llamada cada uno, ya
probados por años de uso en la librería estándar -- reimplementar eso a mano
es más riesgo de un bug sutil que valor real. `audioop` está deprecado desde
Python 3.11 y se elimina en 3.13; si el proyecto actualiza más allá de 3.12,
migrar a `audioop-lts` (paquete de PyPI, mismo API) es un cambio de un import,
no una reescritura.

### Tests

`tests/channels/test_voz.py` (12 tests, todos pasando): conversión de audio
(mulaw↔WAV, resampleo), el detector de turno (silencio puro no dispara, habla
+ silencio sostenido sí, habla corta por debajo del mínimo no cuenta), TwiML,
validación de firma (incluido el fallback de debug sin auth token, y que
delega en `RequestValidator` real en vez de reimplementar), identificación de
ciudadano, y el flujo completo `recibir_turno` → caso creado con
`Canal.voz` (mismo patrón que el test equivalente de WhatsApp). Se agregó
`"voz"` a la lista de canales que mockea la fixture `checkpointer_en_memoria`
(`tests/conftest.py`) y una fixture nueva `mock_asr_tts` que mockea
`voz.transcribir`/`voz.sintetizar` -- nunca se corre faster-whisper/Kokoro de
verdad en un test.

Se corrió además la suite completa del proyecto después de estos cambios
(tocan `conftest.py`, fixture compartida por todos los canales) para
confirmar que no se rompió nada de lo existente.

**Lo que esto NO prueba**: nunca se conectó una llamada real de Twilio contra
este código. Lo verificado es: el protocolo contra la documentación oficial,
la lógica de turno con audio sintético, y el camino hasta `procesar_mensaje`
con el LLM mockeado. Falta una prueba de punta a punta con un número de
Twilio real y un túnel (ngrok) hacia este servidor.

### Qué queda para la próxima sesión

- [ ] Prueba de punta a punta con un número de Twilio real (hace falta cuenta
      de Twilio, número de voz configurado, y un túnel tipo ngrok para
      `voz_websocket_url` en desarrollo).
- [ ] Afinar `UMBRAL_ENERGIA_VOZ`/`CHUNKS_SILENCIO_FIN_TURNO` contra audio de
      una llamada real -- hoy son valores a ojo, no medidos.
- [ ] Resolver cómo se maneja el aviso de IA (`app/agents/aviso_ia.py`) en
      voz: hoy se antepone como texto una sola vez por caso; falta confirmar
      que Kokoro lo sintetiza bien en el primer turno de la llamada real, o
      decidir un mensaje de apertura fijo en vez de reusar el mismo texto.
- [ ] Barge-in (que el ciudadano pueda interrumpir mientras el agente está
      "hablando"): el mensaje `clear` de Twilio ya está verificado en el
      protocolo pero no se usa todavía -- `enviar_audio` no escucha nuevos
      `media` entrantes mientras envía la respuesta.
- [ ] Migración Postgres para sacar el valor huérfano `sms` del enum `canal`
      (no bloquea nada de voz, pendiente de antes).

---

## 2026-10-31 — Teléfono web y la primera conversación de voz de punta a punta

El canal nunca se había probado con audio real: hace falta una línea de Twilio
y un túnel. Para probarlo y para grabar la demo se agregó un **teléfono web**
en el panel (`/telefono`, "Teléfono de prueba"): el navegador captura el
micrófono, lo baja a mu-law de 8 kHz en pedazos de 20 ms y habla el mismo
protocolo que Twilio Media Streams contra `/api/telefono-web/stream`. Del lado
del servidor la llamada pasa por exactamente el mismo código que una de Twilio
(`atender_stream` en `app/api/webhooks.py`); lo único distinto es que pide un
usuario del panel (el token va en el primer mensaje, no en la URL, para que no
quede en los logs) y que el teléfono del ciudadano lo fija el servidor, no un
parámetro que cualquiera podría mandar. La página recibe además subtítulos (lo
que entendió el reconocimiento y lo que contestó el agente) y el estado del
turno.

El códec mu-law del navegador copia el algoritmo de `audioop` (en 14 bits, con
el corrimiento antes del signo): comparado contra Python en los 65.536 valores
de entrada y los 256 de salida, coincide bit a bit. Mientras suena el agente
la página manda silencio: sin cancelación de eco confiable en el navegador, el
detector de turno tomaría la voz del agente por los parlantes como si hablara
el ciudadano.

Las llamadas de prueba (audio sintetizado con Kokoro, enviado a velocidad
real) destaparon cuatro problemas, tres de ellos también de Twilio:

- **La llamada se cortaba en un turno largo.** El turno se procesaba dentro del
  bucle que lee el WebSocket, y el audio sigue llegando mientras tanto (50
  pedazos por segundo, también en silencio). El servidor encola 32 mensajes y,
  lleno, deja de leer el socket, así que no le llegan las respuestas a sus
  pings: un turno de más de unos 20 segundos (el primero, con el modelo
  cargándose, tardó 22) cortaba la llamada. Ahora el turno corre en su propia
  tarea, el bucle sigue leyendo, y el audio que llega mientras se procesa se
  descarta (todavía no hay barge-in).
- **El DNI dictado no se reconocía.** Whisper lo transcribe "30-885-211", con
  guiones; el código solo leía puntos. Ahora acepta guiones y espacios.
- **"El jueves a las diez" no se leía.** Por voz la hora llega en palabras; la
  fecha quedaba en manos del modelo, que reservó el lunes. Ahora se leen las
  horas en palabras ("a las diez", "a la una y media").
- **El DNI registraba un reclamo.** Después de pedir un turno, el mensaje con
  el DNI lo clasifica el intake por sí solo y salió "reclamo"; el agente
  registró el pedido del turno como reclamo. Ahora la respuesta al pedido de
  datos lleva la intención del caso abierto, y un `crear_reclamo` en una
  conversación por un turno se trata como reserva (si no dijo el día, se le
  pregunta). Además el dataset v4 suma turnos después del pedido de datos.

Repetida, la llamada sale entera: saludo, pedido del turno, pedido de datos,
DNI dictado, la grilla de la agenda, "el jueves a las diez" y, como ese horario
estaba ocupado, los tres libres más cercanos.

### Qué queda

- [ ] El primer turno lee el aviso de IA y el de datos personales completos:
      unos 30 segundos de audio. En voz convendría una versión corta, o
      decirlo en el saludo (que hoy ya avisa que es una IA).
- [ ] Probar el teléfono web con un micrófono real (el navegador integrado
      de las pruebas no tiene micrófono: se probó con un oscilador).
- [ ] Barge-in, VAD real, Whisper en la GPU y un aviso de "un momento" mientras
      piensa (ver la lista de mejoras del canal).
