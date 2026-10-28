import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Ban, Trash2, X } from "lucide-react";

import { bloquearDia, configurarAgenda, desbloquearDia, listarBloqueos } from "../lib/turnos";
import type { DiaBloqueado, Turno } from "../lib/tipos";

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

const campo =
  "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-institucional-500";

function fechaLegible(fecha: string): string {
  const [anio, mes, dia] = fecha.split("-");
  return `${dia}/${mes}/${anio}`;
}

/** Configuración de la grilla de una agenda y de los días sin atención. Solo
 * para el supervisor: la API rechaza estos cambios a un operador. */
export function ConfigurarAgenda({
  agenda,
  onCambio,
  onAviso,
  onCerrar,
}: {
  agenda: Turno;
  onCambio: () => Promise<void>;
  onAviso: (mensaje: string) => void;
  onCerrar: () => void;
}) {
  const [sede, setSede] = useState(agenda.sede ?? "");
  const [dias, setDias] = useState<number[]>(agenda.dias_atencion);
  const [apertura, setApertura] = useState(agenda.hora_apertura);
  const [cierre, setCierre] = useState(agenda.hora_cierre);
  const [duracion, setDuracion] = useState(agenda.duracion_minutos);
  const [cupos, setCupos] = useState(agenda.cupos_por_horario);
  const [anticipacion, setAnticipacion] = useState(agenda.anticipacion_maxima_dias);
  const [bloqueos, setBloqueos] = useState<DiaBloqueado[]>([]);
  const [fecha, setFecha] = useState("");
  const [motivo, setMotivo] = useState("");
  const [paraTodas, setParaTodas] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    setSede(agenda.sede ?? "");
    setDias(agenda.dias_atencion);
    setApertura(agenda.hora_apertura);
    setCierre(agenda.hora_cierre);
    setDuracion(agenda.duracion_minutos);
    setCupos(agenda.cupos_por_horario);
    setAnticipacion(agenda.anticipacion_maxima_dias);
  }, [agenda.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function cargarBloqueos() {
    try {
      setBloqueos(await listarBloqueos());
    } catch {
      setBloqueos([]);
    }
  }

  useEffect(() => {
    void cargarBloqueos();
  }, []);

  async function intentar(accion: () => Promise<void>) {
    setGuardando(true);
    try {
      await accion();
      setError(null);
      await onCambio();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  }

  function guardar(evento: FormEvent) {
    evento.preventDefault();
    void intentar(async () => {
      await configurarAgenda(agenda.id, {
        sede: sede.trim() || null,
        dias_atencion: dias,
        hora_apertura: apertura,
        hora_cierre: cierre,
        duracion_minutos: duracion,
        cupos_por_horario: cupos,
        anticipacion_maxima_dias: anticipacion,
      });
      onAviso(`Agenda "${agenda.nombre}" actualizada. Los turnos ya dados no cambian.`);
    });
  }

  function bloquear(evento: FormEvent) {
    evento.preventDefault();
    void intentar(async () => {
      const { afectados } = await bloquearDia({
        fecha,
        motivo: motivo.trim(),
        turno_id: paraTodas ? null : agenda.id,
      });
      setFecha("");
      setMotivo("");
      await cargarBloqueos();
      onAviso(
        afectados.length
          ? `Día bloqueado. Había ${afectados.length} turno(s) dados ese día: revíselos en la grilla para cancelarlos o cambiarlos.`
          : "Día bloqueado. No había turnos dados ese día.",
      );
    });
  }

  const visibles = bloqueos.filter((b) => b.turno_id === null || b.turno_id === agenda.id);

  return (
    <section className="mb-5 rounded-xl border border-institucional-100 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-slate-900">Configurar {agenda.nombre}</h3>
          <p className="text-sm text-slate-600">La grilla nueva vale para los turnos que se den desde ahora.</p>
        </div>
        <button type="button" onClick={onCerrar} className="rounded p-1 text-slate-400 hover:text-slate-700" aria-label="Cerrar configuración">
          <X size={16} aria-hidden />
        </button>
      </div>

      {error && <p className="mb-3 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-2">
        <form onSubmit={guardar} className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Sede</span>
            <input value={sede} onChange={(e) => setSede(e.target.value)} className={campo} />
          </label>
          <div className="text-sm">
            <span className="mb-1 block font-medium text-slate-700">Días de atención</span>
            <div className="flex flex-wrap gap-1.5">
              {DIAS.map((nombre, dia) => {
                const activo = dias.includes(dia);
                return (
                  <button
                    key={nombre}
                    type="button"
                    aria-pressed={activo}
                    onClick={() =>
                      setDias(activo ? dias.filter((d) => d !== dia) : [...dias, dia].sort((a, b) => a - b))
                    }
                    className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                      activo ? "bg-institucional-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                  >
                    {nombre}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Abre</span>
              <input type="time" value={apertura} onChange={(e) => setApertura(e.target.value)} className={campo} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Cierra</span>
              <input type="time" value={cierre} onChange={(e) => setCierre(e.target.value)} className={campo} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Minutos por turno</span>
              <input type="number" min={5} max={240} value={duracion} onChange={(e) => setDuracion(Number(e.target.value))} className={campo} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Personas por horario</span>
              <input type="number" min={1} max={50} value={cupos} onChange={(e) => setCupos(Number(e.target.value))} className={campo} />
            </label>
            <label className="col-span-2 text-sm">
              <span className="mb-1 block font-medium text-slate-700">Se dan turnos con hasta (días de anticipación)</span>
              <input type="number" min={1} max={365} value={anticipacion} onChange={(e) => setAnticipacion(Number(e.target.value))} className={campo} />
            </label>
          </div>
          <button
            type="submit"
            disabled={guardando || dias.length === 0}
            className="rounded-md bg-institucional-600 px-4 py-2 text-sm font-medium text-white hover:bg-institucional-700 disabled:opacity-50"
          >
            Guardar grilla
          </button>
        </form>

        <div>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <Ban size={15} className="text-rose-600" aria-hidden /> Días sin atención
          </h4>
          <form onSubmit={bloquear} className="mb-3 space-y-2 rounded-lg bg-slate-50 p-3">
            <div className="flex gap-2">
              <input type="date" required value={fecha} onChange={(e) => setFecha(e.target.value)} className={`${campo} w-40`} />
              <input
                required
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Motivo, ej.: Feriado nacional"
                className={campo}
              />
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-700">
              <input type="checkbox" checked={paraTodas} onChange={(e) => setParaTodas(e.target.checked)} />
              Para todas las agendas (feriado). Sin marcar, solo para {agenda.nombre}.
            </label>
            <button
              type="submit"
              disabled={guardando}
              className="rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
            >
              Bloquear día
            </button>
          </form>
          {visibles.length === 0 ? (
            <p className="text-sm text-slate-500">No hay días bloqueados próximos.</p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {visibles.map((bloqueo) => (
                <li key={bloqueo.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span>
                    <span className="font-medium tabular-nums text-slate-900">{fechaLegible(bloqueo.fecha)}</span>{" "}
                    <span className="text-slate-600">· {bloqueo.motivo}</span>
                    <span className="ml-1.5 text-xs text-slate-400">
                      {bloqueo.turno_id === null ? "todas las agendas" : "esta agenda"}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      void intentar(async () => {
                        await desbloquearDia(bloqueo.id);
                        await cargarBloqueos();
                      })
                    }
                    className="rounded p-1 text-slate-400 hover:text-rose-700"
                    aria-label={`Desbloquear ${fechaLegible(bloqueo.fecha)}`}
                  >
                    <Trash2 size={14} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
