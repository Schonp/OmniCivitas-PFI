// Audio del teléfono web: el mismo formato que una llamada de Twilio (mu-law a
// 8 kHz, mono, en pedazos de 20 ms), para que el backend no distinga una
// llamada simulada de una real.

export const MUESTRAS_POR_PEDAZO = 160; // 20 ms a 8 kHz
const FRECUENCIA_TELEFONO = 8000;

// Fin de cada segmento de la curva mu-law, en 14 bits.
const FIN_DE_SEGMENTO = [0x3f, 0x7f, 0xff, 0x1ff, 0x3ff, 0x7ff, 0xfff, 0x1fff];

/** Una muestra PCM de 16 bits a mu-law (G.711). Es el algoritmo de
 * `audioop.lin2ulaw` (en 14 bits, con el corrimiento antes del signo), para
 * que el navegador codifique bit a bit igual que el backend. */
export function linealAMulaw(muestra: number): number {
  let valor = Math.max(-32768, Math.min(32767, Math.round(muestra))) >> 2;
  let mascara = 0xff;
  if (valor < 0) {
    valor = -valor;
    mascara = 0x7f;
  }
  valor = Math.min(valor, 8159) + 0x21;
  const segmento = FIN_DE_SEGMENTO.findIndex((fin) => valor <= fin);
  if (segmento === -1) return 0x7f ^ mascara;
  return ((segmento << 4) | ((valor >> (segmento + 1)) & 0x0f)) ^ mascara;
}

/** Un byte mu-law a PCM de 16 bits, igual que `audioop.ulaw2lin`. */
export function mulawALineal(byte: number): number {
  const valor = ~byte & 0xff;
  const signo = valor & 0x80;
  const exponente = (valor >> 4) & 0x07;
  const mantisa = valor & 0x0f;
  const magnitud = (((mantisa << 3) + 0x84) << exponente) - 0x84;
  return signo ? -magnitud : magnitud;
}

/** Silencio en mu-law: lo que se manda mientras habla el agente. */
export const PEDAZO_DE_SILENCIO = new Uint8Array(MUESTRAS_POR_PEDAZO).fill(linealAMulaw(0));

export function codificarPedazo(muestras: Float32Array): Uint8Array {
  const salida = new Uint8Array(muestras.length);
  for (let i = 0; i < muestras.length; i++) {
    salida[i] = linealAMulaw(muestras[i] * 32767);
  }
  return salida;
}

export function decodificarPedazo(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const salida = new Float32Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) {
    salida[i] = mulawALineal(bytes[i]) / 32768;
  }
  return salida;
}

export function aBase64(bytes: Uint8Array): string {
  let binario = "";
  for (const byte of bytes) binario += String.fromCharCode(byte);
  return btoa(binario);
}

export function desdeBase64(texto: string): Uint8Array {
  const binario = atob(texto);
  const bytes = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
  return bytes;
}

/** Nivel de 0 a 1 de un pedazo, para el medidor del micrófono. */
export function nivel(muestras: Float32Array): number {
  let suma = 0;
  for (const muestra of muestras) suma += muestra * muestra;
  return Math.min(1, Math.sqrt(suma / muestras.length) * 4);
}

// Procesador del micrófono, corre en el hilo de audio. Baja de la frecuencia
// de la placa (44,1 o 48 kHz) a 8 kHz con un pasabajos simple y
// interpolación lineal, y entrega pedazos de 20 ms. Va como texto porque un
// AudioWorklet se carga desde una URL propia.
const CODIGO_CAPTURA = `
class CapturaTelefono extends AudioWorkletProcessor {
  constructor() {
    super();
    this.paso = sampleRate / ${FRECUENCIA_TELEFONO};
    this.posicion = 0;
    this.anterior = 0;
    this.filtrada = 0;
    // Pasabajos de un polo a ~3,4 kHz: lo que la telefonía deja pasar.
    this.alfa = 1 - Math.exp((-2 * Math.PI * 3400) / sampleRate);
    this.pendientes = [];
  }

  process(entradas) {
    const canal = entradas[0] && entradas[0][0];
    if (!canal) return true;
    const filtrado = new Float32Array(canal.length);
    for (let i = 0; i < canal.length; i++) {
      this.filtrada += this.alfa * (canal[i] - this.filtrada);
      filtrado[i] = this.filtrada;
    }
    while (this.posicion < filtrado.length - 1) {
      const i = Math.floor(this.posicion);
      const fraccion = this.posicion - i;
      const a = i < 0 ? this.anterior : filtrado[i];
      const b = filtrado[i + 1];
      this.pendientes.push(a + (b - a) * fraccion);
      this.posicion += this.paso;
    }
    this.posicion -= filtrado.length;
    this.anterior = filtrado[filtrado.length - 1];
    while (this.pendientes.length >= ${MUESTRAS_POR_PEDAZO}) {
      const pedazo = Float32Array.from(this.pendientes.splice(0, ${MUESTRAS_POR_PEDAZO}));
      this.port.postMessage(pedazo, [pedazo.buffer]);
    }
    return true;
  }
}
registerProcessor("captura-telefono", CapturaTelefono);
`;

export async function crearCaptura(
  contexto: AudioContext,
  microfono: MediaStream,
  alRecibir: (pedazo: Float32Array) => void,
): Promise<() => void> {
  const url = URL.createObjectURL(new Blob([CODIGO_CAPTURA], { type: "text/javascript" }));
  try {
    await contexto.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const fuente = contexto.createMediaStreamSource(microfono);
  const captura = new AudioWorkletNode(contexto, "captura-telefono");
  captura.port.onmessage = (evento) => alRecibir(evento.data as Float32Array);
  fuente.connect(captura);
  return () => {
    captura.port.onmessage = null;
    fuente.disconnect();
    captura.disconnect();
  };
}

/** Reproduce los pedazos del agente uno detrás de otro, sin cortes. */
export class Reproductor {
  private proximo = 0;
  private readonly contexto: AudioContext;

  constructor(contexto: AudioContext) {
    this.contexto = contexto;
  }

  encolar(bytes: Uint8Array) {
    const muestras = decodificarPedazo(bytes);
    const buffer = this.contexto.createBuffer(1, muestras.length, FRECUENCIA_TELEFONO);
    buffer.copyToChannel(muestras, 0);
    const fuente = this.contexto.createBufferSource();
    fuente.buffer = buffer;
    fuente.connect(this.contexto.destination);
    const ahora = this.contexto.currentTime;
    this.proximo = Math.max(this.proximo, ahora + 0.05);
    fuente.start(this.proximo);
    this.proximo += buffer.duration;
  }

  /** Si todavía queda audio del agente por sonar (más un margen). */
  hablando(margen = 0.3): boolean {
    return this.proximo + margen > this.contexto.currentTime;
  }
}
