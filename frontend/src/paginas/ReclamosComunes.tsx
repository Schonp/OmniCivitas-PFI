import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, Layers, RefreshCw } from "lucide-react";

import { EstadoBadge } from "../componentes/Etiquetas";
import { generarGruposReclamos, listarGruposReclamos } from "../lib/reclamos";
import { formatearFechaHora, idCorto } from "../lib/formato";
import type { GrupoReclamo } from "../lib/tipos";

export function ReclamosComunes() {
  const navegar = useNavigate();
  const [grupos, setGrupos] = useState<GrupoReclamo[]>([]);
  const [cargando, setCargando] = useState(true);
  const [generando, setGenerando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listarGruposReclamos()
      .then(setGrupos)
      .catch((excepcion) =>
        setError(excepcion instanceof Error ? excepcion.message : "No se pudieron cargar los grupos"),
      )
      .finally(() => setCargando(false));
  }, []);

  async function generar() {
    setGenerando(true);
    try {
      setGrupos(await generarGruposReclamos());
      setError(null);
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo agrupar");
    } finally {
      setGenerando(false);
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Reclamos en común</h2>
          <p className="text-sm text-slate-600">
            La IA agrupa los reclamos abiertos que hablan del mismo problema, para detectar
            situaciones que afectan a varios vecinos.
          </p>
        </div>

        <button
          type="button"
          disabled={generando}
          onClick={() => void generar()}
          className="inline-flex items-center gap-2 rounded-md bg-institucional-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-institucional-700 active:translate-y-px disabled:opacity-50"
        >
          <RefreshCw size={15} className={generando ? "animate-spin" : ""} aria-hidden />
          {generando ? "Agrupando…" : "Agrupar con IA"}
        </button>
      </div>

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      {cargando && <p className="text-slate-500">Cargando grupos…</p>}

      {!cargando && grupos.length === 0 && !error && (
        <p className="rounded-lg border border-slate-300 bg-white px-4 py-10 text-center text-slate-600">
          No hay grupos generados. Use «Agrupar con IA» para analizar los reclamos abiertos.
        </p>
      )}

      <div className="space-y-6">
        {grupos.map((grupo) => (
          <section
            key={grupo.id}
            className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          >
            <div className="border-b border-slate-200 px-5 py-4">
              <h3 className="flex items-center gap-2 font-semibold text-slate-900">
                <Layers size={17} className="text-institucional-600" aria-hidden />
                {grupo.tema}
                <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 tabular-nums">
                  {grupo.casos.length} reclamo(s)
                </span>
              </h3>
              <p className="mt-1 text-xs text-slate-500">
                Agrupado por IA el {formatearFechaHora(grupo.generado_en)}. Revise los casos:
                la agrupación es automática.
              </p>
            </div>

            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-5 py-2.5 font-semibold">Caso</th>
                  <th className="px-5 py-2.5 font-semibold">Ciudadano</th>
                  <th className="px-5 py-2.5 font-semibold">Estado</th>
                  <th className="px-5 py-2.5 font-semibold">Creado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {grupo.casos.map((caso) => (
                  <tr
                    key={caso.id}
                    onClick={() => navegar(`/casos/${caso.id}`)}
                    className="cursor-pointer transition hover:bg-institucional-50"
                  >
                    <td className="px-5 py-2.5 font-mono text-xs text-slate-500">
                      {idCorto(caso.id)}
                    </td>
                    <td className="px-5 py-2.5">
                      <div className="font-medium text-slate-900">{caso.ciudadano.nombre}</div>
                      <div className="text-xs text-slate-500">DNI {caso.ciudadano.documento}</div>
                    </td>
                    <td className="px-5 py-2.5">
                      <EstadoBadge estado={caso.estado} />
                    </td>
                    <td className="px-5 py-2.5 tabular-nums text-slate-600">
                      {formatearFechaHora(caso.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>
    </div>
  );
}
