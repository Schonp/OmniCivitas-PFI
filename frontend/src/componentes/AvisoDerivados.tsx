import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, BellOff, X } from "lucide-react";

import { consultarAvisos } from "../lib/casos";
import { ETIQUETA_TIPO, type AvisoCaso } from "../lib/tipos";

// El agente deriva en cualquier momento y el operador puede estar en otra
// pantalla o en otra pestaña: se consulta aunque la pestaña no esté visible,
// que es justamente cuando el sonido hace falta.
const CONSULTA_MS = 10_000;
// Cada consulta vuelve a mirar un rato hacia atrás: una derivación que se
// estaba guardando justo en el momento de la consulta anterior no se pierde.
// Lo que se repite por el solapamiento se descarta con `avisados`.
const SOLAPAMIENTO_MS = 30_000;
const CLAVE_SONIDO = "omnicivitas.aviso_sonoro";

function leerPreferencia(): boolean {
  try {
    return localStorage.getItem(CLAVE_SONIDO) !== "no";
  } catch {
    return true;
  }
}

/** Dos tonos cortos, generados en el navegador: no hace falta un archivo de audio. */
function sonar(contexto: AudioContext) {
  const inicio = contexto.currentTime;
  [880, 660].forEach((frecuencia, indice) => {
    const oscilador = contexto.createOscillator();
    const volumen = contexto.createGain();
    const desde = inicio + indice * 0.18;
    oscilador.frequency.value = frecuencia;
    volumen.gain.setValueAtTime(0.0001, desde);
    volumen.gain.exponentialRampToValueAtTime(0.25, desde + 0.02);
    volumen.gain.exponentialRampToValueAtTime(0.0001, desde + 0.16);
    oscilador.connect(volumen).connect(contexto.destination);
    oscilador.start(desde);
    oscilador.stop(desde + 0.17);
  });
}

/**
 * Avisa con un sonido y una tarjeta cuando llega un caso a la bandeja de quien
 * está mirando: al supervisor, las derivaciones del agente; al operador, los
 * casos que le asignan. También suma el número al título de la pestaña.
 */
export function AvisoDerivados() {
  const [sonido, setSonido] = useState(leerPreferencia);
  const [nuevos, setNuevos] = useState<AvisoCaso[]>([]);
  const avisados = useRef(new Set<string>());
  const audio = useRef<AudioContext | null>(null);
  // La consulta periódica se arma una sola vez: lee la preferencia de ahora.
  const sonidoRef = useRef(sonido);
  useEffect(() => {
    sonidoRef.current = sonido;
  }, [sonido]);

  // Los navegadores no dejan sonar audio hasta que la persona tocó la página:
  // el contexto se crea con el primer clic o tecla y queda listo para después.
  useEffect(() => {
    function habilitar() {
      audio.current ??= new AudioContext();
      void audio.current.resume();
    }
    window.addEventListener("pointerdown", habilitar, { once: true });
    window.addEventListener("keydown", habilitar, { once: true });
    return () => {
      window.removeEventListener("pointerdown", habilitar);
      window.removeEventListener("keydown", habilitar);
    };
  }, []);

  useEffect(() => {
    let activo = true;
    // La primera consulta no lleva `desde`: avisa de lo que llega después de
    // abrir el panel, no de la cola entera.
    let desde: string | undefined;
    async function consultar() {
      try {
        const { ahora, avisos } = await consultarAvisos(desde);
        if (!activo) return;
        desde = new Date(new Date(ahora).getTime() - SOLAPAMIENTO_MS).toISOString();
        const llegados = avisos.filter(
          (aviso) => !avisados.current.has(`${aviso.caso.id} ${aviso.momento}`),
        );
        if (llegados.length === 0) return;
        llegados.forEach((aviso) => avisados.current.add(`${aviso.caso.id} ${aviso.momento}`));
        setNuevos((anteriores) =>
          [
            ...llegados,
            ...anteriores.filter((a) => !llegados.some((l) => l.caso.id === a.caso.id)),
          ].slice(0, 5),
        );
        if (sonidoRef.current && audio.current?.state === "running") {
          sonar(audio.current);
        }
      } catch {
        // Un corte de red no tiene que romper el panel: se reintenta solo.
      }
    }
    void consultar();
    const temporizador = setInterval(() => void consultar(), CONSULTA_MS);
    return () => {
      activo = false;
      clearInterval(temporizador);
    };
  }, []);

  useEffect(() => {
    const base = document.title.replace(/^\(\d+\) /, "");
    document.title = nuevos.length ? `(${nuevos.length}) ${base}` : base;
  }, [nuevos.length]);

  function cambiarSonido() {
    const valor = !sonido;
    setSonido(valor);
    try {
      localStorage.setItem(CLAVE_SONIDO, valor ? "si" : "no");
    } catch {
      // Sin almacenamiento local solo se pierde la preferencia al recargar.
    }
    if (valor && audio.current) sonar(audio.current);
  }

  const descartar = (id: string) => setNuevos((avisos) => avisos.filter((a) => a.caso.id !== id));

  return (
    <>
      <button
        type="button"
        onClick={cambiarSonido}
        aria-pressed={sonido}
        title={sonido ? "Silenciar el aviso de casos derivados" : "Activar el aviso de casos derivados"}
        className="rounded-md border border-institucional-500 p-1.5 transition hover:bg-institucional-600"
      >
        {sonido ? <Bell size={16} aria-hidden /> : <BellOff size={16} aria-hidden />}
        <span className="sr-only">
          {sonido ? "Aviso sonoro activado" : "Aviso sonoro desactivado"}
        </span>
      </button>

      <div
        aria-live="assertive"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {nuevos.map(({ caso, motivo }) => (
          <div
            key={caso.id}
            className="pointer-events-auto rounded-lg border border-rose-200 bg-white p-3 text-slate-800 shadow-lg ring-1 ring-rose-100"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-rose-700">
                {motivo === "derivado" ? "Nuevo caso derivado" : "Le asignaron un caso"}
              </p>
              <button
                type="button"
                onClick={() => descartar(caso.id)}
                className="rounded p-0.5 text-slate-400 hover:text-slate-700"
                aria-label="Cerrar el aviso"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
            <p className="mt-1 text-sm font-medium">{caso.ciudadano.nombre}</p>
            <p className="text-xs text-slate-500">
              {ETIQUETA_TIPO[caso.tipo]} · {caso.referencia}
            </p>
            {caso.operador_asignado && motivo === "derivado" && (
              <p className="text-xs text-slate-500">Asignado a {caso.operador_asignado.nombre}</p>
            )}
            {caso.resumen_ia && (
              <p className="mt-1.5 line-clamp-2 text-xs text-slate-600">{caso.resumen_ia}</p>
            )}
            <Link
              to={`/casos/${caso.id}`}
              onClick={() => descartar(caso.id)}
              className="mt-2 inline-block text-sm font-medium text-institucional-600 hover:underline"
            >
              Abrir el caso
            </Link>
          </div>
        ))}
      </div>
    </>
  );
}
