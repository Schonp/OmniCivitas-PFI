import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, CalendarClock } from "lucide-react";

import { listarTurnos } from "../lib/turnos";
import { formatearFechaHora, idCorto } from "../lib/formato";
import type { Turno } from "../lib/tipos";

export function Turnos() {
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listarTurnos()
      .then(setTurnos)
      .catch((excepcion) =>
        setError(excepcion instanceof Error ? excepcion.message : "No se pudieron cargar los turnos"),
      )
      .finally(() => setCargando(false));
  }, []);

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-xl font-semibold text-slate-900">Turnos y reservas</h2>
        <p className="text-sm text-slate-600">
          Agendas del organismo y las reservas que hizo el agente de IA, para verificar que
          reserva correctamente.
        </p>
      </div>

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      {cargando && <p className="text-slate-500">Cargando turnos…</p>}

      {!cargando && turnos.length === 0 && !error && (
        <p className="rounded-lg border border-slate-300 bg-white px-4 py-10 text-center text-slate-600">
          No hay agendas de turnos cargadas. Ejecute el seed de demostración
          (`python -m scripts.seed_demo`) para crear las agendas de ejemplo.
        </p>
      )}

      <div className="space-y-6">
        {turnos.map((turno) => (
          <section
            key={turno.id}
            className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          >
            <div className="border-b border-slate-200 px-5 py-4">
              <h3 className="flex items-center gap-2 font-semibold text-slate-900">
                <CalendarClock size={17} className="text-institucional-600" aria-hidden />
                {turno.nombre}
                <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 tabular-nums">
                  {turno.reservas.length} reserva(s)
                </span>
              </h3>
              <p className="mt-1 text-sm text-slate-600">{turno.descripcion}</p>
            </div>

            {turno.reservas.length > 0 ? (
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-5 py-2.5 font-semibold">Ciudadano</th>
                    <th className="px-5 py-2.5 font-semibold">Fecha del turno</th>
                    <th className="px-5 py-2.5 font-semibold">Caso</th>
                    <th className="px-5 py-2.5 font-semibold">Reservado el</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {turno.reservas.map((reserva) => (
                    <tr key={reserva.id}>
                      <td className="px-5 py-2.5">
                        <div className="font-medium text-slate-900">{reserva.ciudadano.nombre}</div>
                        <div className="text-xs text-slate-500">
                          DNI {reserva.ciudadano.documento}
                        </div>
                      </td>
                      <td className="px-5 py-2.5 tabular-nums text-slate-700">
                        {formatearFechaHora(reserva.fecha_hora)}
                      </td>
                      <td className="px-5 py-2.5">
                        <Link
                          to={`/casos/${reserva.caso_id}`}
                          className="font-mono text-xs text-institucional-600 hover:underline"
                        >
                          {idCorto(reserva.caso_id)}
                        </Link>
                      </td>
                      <td className="px-5 py-2.5 tabular-nums text-slate-600">
                        {formatearFechaHora(reserva.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="px-5 py-6 text-sm text-slate-500">
                Todavía no hay reservas del agente en esta agenda.
              </p>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
