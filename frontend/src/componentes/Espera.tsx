import { AlertTriangle } from "lucide-react";

const HORAS_DEMORA = 24;

/** Cuánto hace que el ciudadano espera respuesta. El resaltado marca la demora
 * que la tesis identifica como causa de abandono. */
export function Espera({ desde }: { desde: string | null }) {
  if (desde === null) {
    return <span className="text-slate-400">—</span>;
  }

  const horas = (Date.now() - new Date(desde).getTime()) / 3_600_000;
  const demorado = horas >= HORAS_DEMORA;
  const texto =
    horas < 1
      ? `${Math.max(Math.round(horas * 60), 1)} min`
      : horas < 48
        ? `${Math.round(horas)} h`
        : `${Math.round(horas / 24)} días`;

  if (!demorado) {
    return <span className="tabular-nums text-slate-600">{texto}</span>;
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-rose-100 px-2 py-0.5 font-medium text-rose-900 ring-1 ring-inset ring-rose-300">
      <AlertTriangle size={13} aria-hidden />
      <span className="tabular-nums">{texto}</span>
    </span>
  );
}
