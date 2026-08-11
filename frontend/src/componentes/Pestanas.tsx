import type { KeyboardEvent } from "react";

export interface Pestana {
  id: string;
  etiqueta: string;
  contador?: number;
}

interface PestanasProps {
  pestanas: Pestana[];
  activa: string;
  onCambiar: (id: string) => void;
  etiquetaAria: string;
}

export function Pestanas({ pestanas, activa, onCambiar, etiquetaAria }: PestanasProps) {
  function navegarConTeclado(evento: KeyboardEvent<HTMLDivElement>) {
    const direccion =
      evento.key === "ArrowRight" ? 1 : evento.key === "ArrowLeft" ? -1 : 0;
    if (direccion === 0) {
      return;
    }
    evento.preventDefault();
    const actual = pestanas.findIndex((pestana) => pestana.id === activa);
    const siguiente = (actual + direccion + pestanas.length) % pestanas.length;
    onCambiar(pestanas[siguiente].id);
    document.getElementById(`pestana-${pestanas[siguiente].id}`)?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={etiquetaAria}
      onKeyDown={navegarConTeclado}
      className="flex gap-1 border-b border-slate-200"
    >
      {pestanas.map((pestana) => {
        const seleccionada = pestana.id === activa;
        return (
          <button
            key={pestana.id}
            id={`pestana-${pestana.id}`}
            role="tab"
            type="button"
            aria-selected={seleccionada}
            aria-controls={`panel-${pestana.id}`}
            tabIndex={seleccionada ? 0 : -1}
            onClick={() => onCambiar(pestana.id)}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
              seleccionada
                ? "border-institucional-600 text-institucional-700"
                : "border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900"
            }`}
          >
            {pestana.etiqueta}
            {pestana.contador !== undefined && (
              <span
                className={`rounded-full px-1.5 text-xs tabular-nums ${
                  seleccionada
                    ? "bg-institucional-50 text-institucional-700"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {pestana.contador}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

interface PanelPestanaProps {
  id: string;
  activa: string;
  children: React.ReactNode;
}

export function PanelPestana({ id, activa, children }: PanelPestanaProps) {
  if (id !== activa) {
    return null;
  }
  return (
    <div
      id={`panel-${id}`}
      role="tabpanel"
      aria-labelledby={`pestana-${id}`}
      tabIndex={0}
      className="pt-6 outline-none"
    >
      {children}
    </div>
  );
}
