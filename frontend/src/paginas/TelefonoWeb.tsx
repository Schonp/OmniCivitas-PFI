import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { AlertCircle, Loader2, Mic, Phone, PhoneOff, Volume2 } from "lucide-react";

import { tokenStore } from "../lib/api";
import {
  aBase64,
  codificarPedazo,
  crearCaptura,
  desdeBase64,
  nivel,
  PEDAZO_DE_SILENCIO,
  Reproductor,
} from "../lib/audioTelefono";

type Estado = "inactiva" | "conectando" | "escuchando" | "procesando" | "hablando";

interface Linea {
  quien: "ciudadano" | "agente";
  texto: string;
}

interface Llamada {
  socket: WebSocket;
  contexto: AudioContext;
  microfono: MediaStream;
  reproductor: Reproductor;
  detenerCaptura?: () => void;
  intervalo: number;
  procesando: boolean;
}

const CLAVE_TELEFONO = "omnicivitas.telefono_web";

const MOTIVO_DE_CIERRE: Record<number, string> = {
  4401: "La sesión venció o no tiene permiso: vuelva a iniciar sesión.",
  4422: "El número no es válido. Escríbalo en formato internacional, por ejemplo +5491123456789.",
};

const ETIQUETA_ESTADO: Record<Estado, string> = {
  inactiva: "Sin llamada",
  conectando: "Conectando…",
  escuchando: "Escuchando",
  procesando: "El agente está pensando…",
  hablando: "El agente está hablando",
};

function urlDelStream(): string {
  const base = import.meta.env.VITE_API_URL as string | undefined;
  const origen = base
    ? base.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
  return `${origen}/api/telefono-web/stream`;
}

function leerTelefonoGuardado(): string {
  try {
    return localStorage.getItem(CLAVE_TELEFONO) ?? "";
  } catch {
    return "";
  }
}

export function TelefonoWeb() {
  const [telefono, setTelefono] = useState(leerTelefonoGuardado);
  const [estado, setEstado] = useState<Estado>("inactiva");
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [error, setError] = useState<string | null>(null);
  const llamada = useRef<Llamada | null>(null);
  const medidor = useRef<HTMLDivElement>(null);
  const transcripcion = useRef<HTMLDivElement>(null);

  useEffect(() => {
    transcripcion.current?.scrollTo({ top: transcripcion.current.scrollHeight });
  }, [lineas]);

  // Si se sale de la página con la llamada en curso, se corta.
  useEffect(() => () => colgar(), []);

  function colgar(motivo?: string) {
    const actual = llamada.current;
    if (!actual) return;
    llamada.current = null;
    window.clearInterval(actual.intervalo);
    actual.detenerCaptura?.();
    actual.microfono.getTracks().forEach((pista) => pista.stop());
    void actual.contexto.close();
    if (actual.socket.readyState === WebSocket.OPEN) {
      actual.socket.send(JSON.stringify({ event: "stop" }));
    }
    actual.socket.close();
    if (medidor.current) medidor.current.style.width = "0%";
    setEstado("inactiva");
    if (motivo) setError(motivo);
  }

  async function llamar(evento: FormEvent) {
    evento.preventDefault();
    if (llamada.current || telefono.trim() === "") return;
    setError(null);
    setLineas([]);
    setEstado("conectando");
    try {
      localStorage.setItem(CLAVE_TELEFONO, telefono.trim());
    } catch {
      // Sin almacenamiento local solo se pierde el número recordado.
    }

    let microfono: MediaStream;
    try {
      microfono = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      setEstado("inactiva");
      setError("No se pudo usar el micrófono. Revise el permiso del navegador.");
      return;
    }

    const contexto = new AudioContext();
    await contexto.resume();
    const socket = new WebSocket(urlDelStream());
    const actual: Llamada = {
      socket,
      contexto,
      microfono,
      reproductor: new Reproductor(contexto),
      // El estado visible sale de dos cosas: si el backend avisó que está
      // procesando un turno y si todavía suena audio del agente.
      intervalo: window.setInterval(() => {
        if (llamada.current !== actual || !actual.detenerCaptura) return;
        if (actual.reproductor.hablando(0)) setEstado("hablando");
        else if (actual.procesando) setEstado("procesando");
        else setEstado("escuchando");
      }, 150),
      procesando: false,
    };
    llamada.current = actual;
    const streamSid = crypto.randomUUID();

    socket.onopen = () => {
      socket.send(JSON.stringify({ event: "auth", token: tokenStore.get(), telefono: telefono.trim() }));
    };

    socket.onmessage = async (mensaje) => {
      const datos = JSON.parse(String(mensaje.data));
      switch (datos.event) {
        case "conectado": {
          socket.send(JSON.stringify({ event: "start", start: { streamSid, customParameters: {} } }));
          actual.detenerCaptura = await crearCaptura(contexto, microfono, (pedazo) => {
            if (socket.readyState !== WebSocket.OPEN) return;
            // Mientras habla el agente se manda silencio: sin eso, el
            // micrófono levanta la voz del agente por los parlantes y el
            // detector de turno la toma como si hablara el ciudadano.
            const hablaElAgente = actual.reproductor.hablando();
            const bytes = hablaElAgente ? PEDAZO_DE_SILENCIO : codificarPedazo(pedazo);
            socket.send(
              JSON.stringify({ event: "media", streamSid, media: { payload: aBase64(bytes) } }),
            );
            if (medidor.current) {
              medidor.current.style.width = `${hablaElAgente ? 0 : nivel(pedazo) * 100}%`;
            }
          });
          break;
        }
        case "media":
          actual.reproductor.encolar(desdeBase64(datos.media.payload));
          break;
        case "procesando":
          actual.procesando = true;
          break;
        case "listo":
          actual.procesando = false;
          break;
        case "subtitulo":
          setLineas((anteriores) => [...anteriores, { quien: datos.quien, texto: datos.texto }]);
          break;
      }
    };

    socket.onerror = () => {
      colgar("No se pudo conectar con la API. ¿Está corriendo?");
    };

    socket.onclose = (cierre) => {
      if (llamada.current !== actual) return;
      colgar(MOTIVO_DE_CIERRE[cierre.code] ?? "Se cortó la llamada.");
    };
  }

  const enLlamada = estado !== "inactiva";

  return (
    <section>
      <div className="mb-5">
        <h2 className="text-xl font-semibold text-slate-900">Teléfono de prueba</h2>
        <p className="text-sm text-slate-600">
          Simula una llamada al organismo con el micrófono de esta computadora. Pasa por el mismo
          camino que una llamada real: detección del fin de cada frase, reconocimiento de voz,
          agente y voz sintetizada. Hace falta el servicio de voz (<code>voz_asr_tts</code>)
          corriendo.
        </p>
      </div>

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <form
          onSubmit={llamar}
          className="h-fit rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <label className="text-sm">
            <span className="mb-1 block font-medium text-slate-700">Llama desde el número</span>
            <input
              type="tel"
              value={telefono}
              onChange={(e) => setTelefono(e.target.value)}
              disabled={enLlamada}
              placeholder="+5491123456789"
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100 disabled:bg-slate-50"
            />
          </label>
          <p className="mt-1 text-xs text-slate-500">
            Con el número de un vecino que ya escribió por WhatsApp, el agente lo reconoce y
            retoma sus casos.
          </p>

          {/* Las `key` distintas hacen que React cree otro botón: si reusara
              el mismo, al colgar le cambiaría el tipo a "submit" durante el
              mismo clic y el formulario volvería a llamar. */}
          {enLlamada ? (
            <button
              key="colgar"
              type="button"
              onClick={(evento) => {
                evento.preventDefault();
                colgar();
              }}
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-rose-700 active:translate-y-px"
            >
              <PhoneOff size={16} aria-hidden />
              Colgar
            </button>
          ) : (
            <button
              key="llamar"
              type="submit"
              disabled={telefono.trim() === ""}
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-institucional-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-institucional-700 active:translate-y-px disabled:opacity-50"
            >
              <Phone size={16} aria-hidden />
              Llamar
            </button>
          )}

          <div className="mt-5 border-t border-slate-100 pt-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-700" aria-live="polite">
              {estado === "conectando" || estado === "procesando" ? (
                <Loader2 size={16} className="animate-spin text-institucional-600" aria-hidden />
              ) : estado === "hablando" ? (
                <Volume2 size={16} className="text-institucional-600" aria-hidden />
              ) : (
                <Mic size={16} className={enLlamada ? "text-emerald-600" : "text-slate-400"} aria-hidden />
              )}
              {ETIQUETA_ESTADO[estado]}
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden>
              <div ref={medidor} className="h-full w-0 bg-emerald-500 transition-[width] duration-75" />
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Hable y haga una pausa al terminar: el agente contesta cuando detecta medio segundo de
              silencio. Mientras habla el agente, el micrófono no se escucha.
            </p>
          </div>
        </form>

        <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <h3 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
            Lo que se dijo
          </h3>
          <div ref={transcripcion} className="max-h-[28rem] min-h-[16rem] space-y-3 overflow-y-auto p-5">
            {lineas.length === 0 && (
              <p className="text-sm text-slate-500">
                Acá aparece lo que entendió el reconocimiento de voz y lo que contestó el agente.
              </p>
            )}
            {lineas.map((linea, indice) => (
              <div
                key={indice}
                className={`flex ${linea.quien === "ciudadano" ? "justify-end" : "justify-start"}`}
              >
                <p
                  className={`max-w-[80%] whitespace-pre-line rounded-lg px-3 py-2 text-sm ${
                    linea.quien === "ciudadano"
                      ? "bg-institucional-600 text-white"
                      : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {linea.texto}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
