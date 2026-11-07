import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowRightLeft,
  Ban,
  BellRing,
  CalendarClock,
  CalendarPlus,
  CalendarX,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  MapPin,
  Settings2,
  UserCheck,
  UserX,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "../auth";
import { ConfigurarAgenda } from "./ConfigurarAgenda";
import {
  alternativasDe,
  cancelarReserva,
  enviarRecordatorios,
  listarTurnos,
  registrarAsistencia,
  reprogramarReserva,
  reservarDesdePanel,
  type CanalDeReserva,
} from "../lib/turnos";
import {
  ETIQUETA_ESTADO_RESERVA,
  type EstadoReserva,
  type Reserva,
  type Turno,
} from "../lib/tipos";

// Los turnos son del organismo, en hora argentina, sin importar dónde esté
// abierto el navegador: la grilla y las reservas se comparan en esa zona.
const ZONA = "America/Argentina/Buenos_Aires";
const REFRESCO_MS = 15_000;
const DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

const partes = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONA,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** "2026-10-29" y "09:30" de un instante, en hora argentina. */
export function enArgentina(instante: Date): { fecha: string; hora: string } {
  const p = Object.fromEntries(partes.formatToParts(instante).map((x) => [x.type, x.value]));
  return { fecha: `${p.year}-${p.month}-${p.day}`, hora: `${p.hour}:${p.minute}` };
}

function aFecha(fecha: string): Date {
  const [anio, mes, dia] = fecha.split("-").map(Number);
  return new Date(Date.UTC(anio, mes - 1, dia, 12));
}

function sumarDias(fecha: string, dias: number): string {
  const d = aFecha(fecha);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

/** 0 es lunes, como en el backend. */
const diaDeSemana = (fecha: string) => (aFecha(fecha).getUTCDay() + 6) % 7;
const lunesDe = (fecha: string) => sumarDias(fecha, -diaDeSemana(fecha));

export function etiquetaDia(fecha: string): string {
  const d = aFecha(fecha);
  return `${DIAS_CORTOS[diaDeSemana(fecha)]} ${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
}

const diaLargo = new Intl.DateTimeFormat("es-AR", {
  timeZone: "UTC",
  weekday: "long",
  day: "numeric",
  month: "long",
});

function etiquetaDiaLarga(fecha: string): string {
  const texto = diaLargo.format(aFecha(fecha));
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function etiquetaSemana(lunes: string): string {
  const inicio = aFecha(lunes);
  const fin = aFecha(sumarDias(lunes, 6));
  return `${inicio.getUTCDate()} ${MESES[inicio.getUTCMonth()]} al ${fin.getUTCDate()} ${MESES[fin.getUTCMonth()]}`;
}

export function horariosDelDia(agenda: Turno, fecha: string): string[] {
  if (!agenda.dias_atencion.includes(diaDeSemana(fecha))) return [];
  const aMinutos = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
  const horarios: string[] = [];
  for (
    let m = aMinutos(agenda.hora_apertura);
    m + agenda.duracion_minutos <= aMinutos(agenda.hora_cierre);
    m += agenda.duracion_minutos
  ) {
    horarios.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
  }
  return horarios;
}

const OCUPA_LUGAR: EstadoReserva[] = ["confirmada", "atendida", "ausente"];

const COLOR_ESTADO: Record<EstadoReserva, string> = {
  confirmada: "bg-blue-100 text-blue-900 ring-blue-300",
  atendida: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  ausente: "bg-amber-100 text-amber-900 ring-amber-300",
  cancelada: "bg-slate-200 text-slate-600 ring-slate-300",
};

function EstadoTurno({ estado }: { estado: EstadoReserva }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${COLOR_ESTADO[estado]}`}
    >
      {ETIQUETA_ESTADO_RESERVA[estado]}
    </span>
  );
}

function Indicador({
  icono: Icono,
  etiqueta,
  valor,
  detalle,
}: {
  icono: LucideIcon;
  etiqueta: string;
  valor: string;
  detalle: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-sm text-slate-600">
        <Icono size={15} className="text-slate-400" aria-hidden />
        {etiqueta}
      </div>
      <div className="mt-1.5 text-3xl font-semibold text-slate-900">{valor}</div>
      <div className="mt-0.5 text-xs text-slate-500">{detalle}</div>
    </div>
  );
}

interface Seleccion {
  fecha: string;
  hora: string;
}

export function Turnos() {
  const { usuario } = useAuth();
  const esSupervisor = usuario?.rol === "supervisor";
  const hoy = enArgentina(new Date()).fecha;
  const [configurando, setConfigurando] = useState(false);
  const [vista, setVista] = useState<"semana" | "dia">("semana");
  const [aviso, setAviso] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [lunes, setLunes] = useState(() => lunesDe(hoy));
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [agendaId, setAgendaId] = useState<string | null>(null);
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null);
  const [filtro, setFiltro] = useState<EstadoReserva | "todos">("todos");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ahora, setAhora] = useState(() => enArgentina(new Date()));

  const cargar = useCallback(async () => {
    try {
      setTurnos(await listarTurnos(lunes, 7));
      setAhora(enArgentina(new Date()));
      setError(null);
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudieron cargar los turnos");
    } finally {
      setCargando(false);
    }
  }, [lunes]);

  // Se refresca solo: una reserva que hace el agente por WhatsApp aparece en la
  // grilla sin recargar la página.
  useEffect(() => {
    void cargar();
    const temporizador = setInterval(() => void cargar(), REFRESCO_MS);
    return () => clearInterval(temporizador);
  }, [cargar]);

  const agenda = turnos.find((t) => t.id === agendaId) ?? turnos[0];
  const ahoraClave = `${ahora.fecha} ${ahora.hora}`;
  const bloqueados = useMemo(
    () => new Map((agenda?.bloqueos ?? []).map((b) => [b.fecha, b.motivo])),
    [agenda],
  );

  async function recordar() {
    setEnviando(true);
    try {
      const resumen = await enviarRecordatorios();
      setAviso(
        resumen.total === 0
          ? "No hay turnos de mañana pendientes de recordatorio."
          : `Recordatorios de mañana: ${resumen.enviados} enviados de ${resumen.total}.` +
              (resumen.no_enviados.length
                ? ` No salieron ${resumen.no_enviados.length} (${resumen.no_enviados[0].motivo}); se reintentan en el próximo envío.`
                : ""),
      );
      await cargar();
    } catch (excepcion) {
      setAviso(excepcion instanceof Error ? excepcion.message : "No se pudieron enviar los recordatorios");
    } finally {
      setEnviando(false);
    }
  }

  const reservasPorHorario = useMemo(() => {
    const mapa = new Map<string, Reserva[]>();
    for (const reserva of agenda?.reservas ?? []) {
      const { fecha, hora } = enArgentina(new Date(reserva.fecha_hora));
      const clave = `${fecha} ${hora}`;
      mapa.set(clave, [...(mapa.get(clave) ?? []), reserva]);
    }
    return mapa;
  }, [agenda]);

  const dias = useMemo(() => {
    if (!agenda) return [];
    return Array.from({ length: 7 }, (_, i) => sumarDias(lunes, i)).filter((fecha) =>
      agenda.dias_atencion.includes(diaDeSemana(fecha)),
    );
  }, [agenda, lunes]);

  const filas = useMemo(() => {
    const horas = new Set<string>();
    for (const fecha of dias) horariosDelDia(agenda!, fecha).forEach((h) => horas.add(h));
    return [...horas].sort();
  }, [agenda, dias]);

  const listado = (agenda?.reservas ?? []).filter((r) => filtro === "todos" || r.estado === filtro);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Turnos</h2>
          <p className="text-sm text-slate-600">
            {vista === "dia"
              ? "Los turnos del día de todas las agendas, en orden de hora, para llamar a cada vecino y marcar si vino."
              : "Agenda semanal de cada trámite: horarios libres, ocupados y la asistencia de cada vecino."}{" "}
            Se actualiza sola cada 15 segundos.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <div
            role="group"
            aria-label="Vista"
            className="mr-2 inline-flex rounded-md border border-slate-300 bg-white p-0.5"
          >
            {(["dia", "semana"] as const).map((opcion) => (
              <button
                key={opcion}
                type="button"
                aria-pressed={vista === opcion}
                onClick={() => setVista(opcion)}
                className={`rounded px-3 py-1 text-sm font-medium transition ${
                  vista === opcion
                    ? "bg-institucional-600 text-white"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                {opcion === "dia" ? "Día" : "Semana"}
              </button>
            ))}
          </div>
          {vista === "semana" && (
            <>
              <button
                type="button"
                onClick={() => setLunes(sumarDias(lunes, -7))}
                className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:border-institucional-500"
                aria-label="Semana anterior"
              >
                <ChevronLeft size={16} aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => setLunes(lunesDe(hoy))}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:border-institucional-500"
              >
                Hoy
              </button>
              <button
                type="button"
                onClick={() => setLunes(sumarDias(lunes, 7))}
                className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:border-institucional-500"
                aria-label="Semana siguiente"
              >
                <ChevronRight size={16} aria-hidden />
              </button>
              <span className="ml-2 text-sm font-medium text-slate-700">Semana del {etiquetaSemana(lunes)}</span>
            </>
          )}
          {esSupervisor && agenda && (
            <>
              <button
                type="button"
                disabled={enviando}
                onClick={() => void recordar()}
                className="ml-3 inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:border-institucional-500 disabled:opacity-50"
              >
                <BellRing size={15} aria-hidden />
                {enviando ? "Enviando…" : "Recordar turnos de mañana"}
              </button>
              <button
                type="button"
                onClick={() => setConfigurando((valor) => !valor)}
                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium ${
                  configurando
                    ? "border-institucional-500 bg-institucional-50 text-institucional-700"
                    : "border-slate-300 bg-white text-slate-700 hover:border-institucional-500"
                }`}
              >
                <Settings2 size={15} aria-hidden />
                Configurar agenda
              </button>
            </>
          )}
        </div>
      </div>

      {aviso && (
        <p className="mb-4 flex items-start justify-between gap-2 rounded-md bg-institucional-50 px-3 py-2 text-sm text-institucional-900">
          <span className="flex items-center gap-2">
            <CheckCircle2 size={16} aria-hidden />
            {aviso}
          </span>
          <button type="button" onClick={() => setAviso(null)} aria-label="Cerrar aviso">
            <X size={14} aria-hidden />
          </button>
        </p>
      )}

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

      {vista === "dia" && turnos.length > 0 && <VistaDelDia hoy={hoy} />}

      {vista === "semana" && agenda && (
        <>
          <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label="Agendas">
            {turnos.map((t) => {
              const activa = t.id === agenda.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={activa}
                  onClick={() => {
                    setAgendaId(t.id);
                    setSeleccion(null);
                  }}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                    activa
                      ? "border-institucional-500 bg-institucional-50 text-institucional-900 ring-1 ring-institucional-500"
                      : "border-slate-200 bg-white text-slate-700 hover:border-institucional-500"
                  }`}
                >
                  <div className="font-medium">{t.nombre}</div>
                </button>
              );
            })}
          </div>

          <p className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600">
            {agenda.sede && (
              <span className="inline-flex items-center gap-1">
                <MapPin size={14} className="text-slate-400" aria-hidden />
                {agenda.sede}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <CalendarClock size={14} className="text-slate-400" aria-hidden />
              {agenda.horario.charAt(0).toUpperCase() + agenda.horario.slice(1)}
            </span>
            <span className="inline-flex items-center gap-1">
              <Users size={14} className="text-slate-400" aria-hidden />
              {agenda.cupos_por_horario === 1
                ? "1 persona por horario"
                : `${agenda.cupos_por_horario} personas por horario`}
            </span>
          </p>

          {configurando && esSupervisor && (
            <ConfigurarAgenda
              agenda={agenda}
              onCambio={cargar}
              onAviso={setAviso}
              onCerrar={() => setConfigurando(false)}
            />
          )}

          <div className="grid gap-5 xl:grid-cols-[1fr_20rem]">
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
              <table className="min-w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="w-16 px-2 py-2.5 text-left text-xs font-semibold text-slate-500">Hora</th>
                    {dias.map((fecha) => (
                      <th
                        key={fecha}
                        className={`px-2 py-2.5 text-left text-xs font-semibold uppercase tracking-wide ${
                          fecha === hoy ? "text-institucional-700" : "text-slate-600"
                        }`}
                      >
                        {etiquetaDia(fecha)}
                        {fecha === hoy && (
                          <span className="ml-1.5 rounded bg-institucional-600 px-1.5 py-0.5 text-[10px] text-white">
                            hoy
                          </span>
                        )}
                        {bloqueados.has(fecha) && (
                          <span className="mt-0.5 flex items-center gap-1 text-[10px] font-medium normal-case text-rose-700">
                            <Ban size={11} aria-hidden />
                            {bloqueados.get(fecha)}
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filas.map((hora) => (
                    <tr key={hora} className="border-b border-slate-100 last:border-0">
                      <td className="px-2 py-1 align-top text-xs tabular-nums text-slate-500">{hora}</td>
                      {dias.map((fecha) => {
                        if (!horariosDelDia(agenda, fecha).includes(hora)) {
                          return <td key={fecha} className="bg-slate-50" />;
                        }
                        if (bloqueados.has(fecha)) {
                          // Los turnos que ya estaban dados ese día se siguen
                          // viendo, para cancelarlos o cambiarlos.
                          const pendientes = (reservasPorHorario.get(`${fecha} ${hora}`) ?? []).filter(
                            (r) => r.estado === "confirmada",
                          );
                          return (
                            <td key={fecha} className="p-1 align-top">
                              {pendientes.length ? (
                                <button
                                  type="button"
                                  onClick={() => setSeleccion({ fecha, hora })}
                                  className="flex min-h-11 w-full min-w-28 flex-col rounded-md border border-rose-300 bg-rose-100 px-2 py-1 text-left text-xs text-rose-900 hover:brightness-95"
                                >
                                  <span className="font-medium">A reprogramar</span>
                                  {pendientes.slice(0, 2).map((r) => (
                                    <span key={r.id} className="truncate">{r.ciudadano.nombre.split(" ")[0]}</span>
                                  ))}
                                </button>
                              ) : (
                                <div className="flex min-h-11 min-w-28 items-center rounded-md border border-dashed border-rose-200 bg-rose-50/50 px-2 text-xs text-rose-700">
                                  Sin atención
                                </div>
                              )}
                            </td>
                          );
                        }
                        const clave = `${fecha} ${hora}`;
                        const reservas = reservasPorHorario.get(clave) ?? [];
                        const ocupan = reservas.filter((r) => OCUPA_LUGAR.includes(r.estado));
                        const libres = agenda.cupos_por_horario - ocupan.length;
                        const pasado = clave <= ahoraClave;
                        const elegida = seleccion?.fecha === fecha && seleccion.hora === hora;
                        const estilo = pasado
                          ? "bg-slate-50 text-slate-400 border-slate-200"
                          : libres <= 0
                            ? "bg-institucional-600 text-white border-institucional-600"
                            : ocupan.length > 0
                              ? "bg-amber-50 text-amber-900 border-amber-200"
                              : "bg-emerald-50/60 text-emerald-800 border-emerald-100";
                        return (
                          <td key={fecha} className="p-1 align-top">
                            <button
                              type="button"
                              onClick={() => setSeleccion({ fecha, hora })}
                              className={`flex h-full min-h-11 w-full min-w-28 flex-col rounded-md border px-2 py-1 text-left text-xs transition hover:brightness-95 ${estilo} ${
                                elegida ? "ring-2 ring-institucional-500 ring-offset-1" : ""
                              }`}
                            >
                              <span className="font-medium">
                                {pasado
                                  ? ocupan.length
                                    ? `${ocupan.length} con turno`
                                    : ""
                                  : libres <= 0
                                    ? "Completo"
                                    : libres === agenda.cupos_por_horario
                                      ? "Libre"
                                      : `${libres} libre${libres > 1 ? "s" : ""}`}
                              </span>
                              {ocupan.slice(0, 2).map((r) => (
                                <span key={r.id} className="truncate opacity-90">
                                  {r.ciudadano.nombre.split(" ")[0]}
                                </span>
                              ))}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <DetalleHorario
              agenda={agenda}
              seleccion={seleccion}
              reservas={seleccion ? reservasPorHorario.get(`${seleccion.fecha} ${seleccion.hora}`) ?? [] : []}
              pasado={seleccion ? `${seleccion.fecha} ${seleccion.hora}` <= ahoraClave : false}
              bloqueo={seleccion ? bloqueados.get(seleccion.fecha) ?? null : null}
              onCerrar={() => setSeleccion(null)}
              onCambio={cargar}
              onElegir={setSeleccion}
            />
          </div>

          <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
              <h3 className="font-semibold text-slate-900">Turnos de la semana: {agenda.nombre}</h3>
              <div className="flex flex-wrap gap-1.5">
                {(["todos", "confirmada", "atendida", "ausente", "cancelada"] as const).map((estado) => (
                  <button
                    key={estado}
                    type="button"
                    onClick={() => setFiltro(estado)}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      filtro === estado
                        ? "bg-institucional-600 text-white"
                        : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                  >
                    {estado === "todos" ? "Todos" : ETIQUETA_ESTADO_RESERVA[estado]}
                  </button>
                ))}
              </div>
            </div>
            {listado.length > 0 ? (
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-5 py-2.5 font-semibold">Día y hora</th>
                    <th className="px-5 py-2.5 font-semibold">Ciudadano</th>
                    <th className="px-5 py-2.5 font-semibold">Caso</th>
                    <th className="px-5 py-2.5 font-semibold">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {listado.map((reserva) => {
                    const { fecha, hora } = enArgentina(new Date(reserva.fecha_hora));
                    return (
                      <tr
                        key={reserva.id}
                        onClick={() => setSeleccion({ fecha, hora })}
                        className="cursor-pointer hover:bg-slate-50"
                      >
                        <td className="px-5 py-2.5 tabular-nums text-slate-700">
                          {etiquetaDia(fecha)} · {hora}
                        </td>
                        <td className="px-5 py-2.5">
                          <div className="font-medium text-slate-900">{reserva.ciudadano.nombre}</div>
                          <div className="text-xs text-slate-500">DNI {reserva.ciudadano.documento}</div>
                        </td>
                        <td className="px-5 py-2.5">
                          <Link
                            to={`/casos/${reserva.caso_id}`}
                            onClick={(evento) => evento.stopPropagation()}
                            className="font-mono text-xs text-institucional-600 hover:underline"
                          >
                            {reserva.referencia}
                          </Link>
                        </td>
                        <td className="px-5 py-2.5">
                          <EstadoTurno estado={reserva.estado} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="px-5 py-6 text-sm text-slate-500">No hay turnos con ese estado en la semana.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function DetalleHorario({
  agenda,
  seleccion,
  reservas,
  pasado,
  bloqueo,
  onCerrar,
  onCambio,
  onElegir,
}: {
  agenda: Turno;
  seleccion: Seleccion | null;
  reservas: Reserva[];
  pasado: boolean;
  bloqueo: string | null;
  onCerrar: () => void;
  onCambio: () => Promise<void>;
  onElegir: (seleccion: Seleccion) => void;
}) {
  const [cancelando, setCancelando] = useState<string | null>(null);
  const [moviendo, setMoviendo] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [nuevaFecha, setNuevaFecha] = useState("");
  const [nuevaHora, setNuevaHora] = useState("");
  const [reservando, setReservando] = useState(false);
  const [documento, setDocumento] = useState("");
  const [nombre, setNombre] = useState("");
  const [canal, setCanal] = useState<CanalDeReserva>("voz");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alternativas, setAlternativas] = useState<string[]>([]);

  useEffect(() => {
    setCancelando(null);
    setMoviendo(null);
    setReservando(false);
    setMotivo("");
    setError(null);
    setAlternativas([]);
  }, [seleccion?.fecha, seleccion?.hora]);

  async function ejecutar(accion: () => Promise<unknown>) {
    setOcupado(true);
    try {
      await accion();
      setCancelando(null);
      setMoviendo(null);
      setReservando(false);
      setMotivo("");
      setDocumento("");
      setNombre("");
      setError(null);
      setAlternativas([]);
      await onCambio();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo completar la acción");
      setAlternativas(alternativasDe(excepcion));
    } finally {
      setOcupado(false);
    }
  }

  const ocupanLugar = reservas.filter((r) => OCUPA_LUGAR.includes(r.estado)).length;
  const hayLugar = !pasado && !bloqueo && ocupanLugar < agenda.cupos_por_horario;

  if (!seleccion) {
    return (
      <aside className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-600">
        <p className="font-medium text-slate-800">Seleccione un horario</p>
        <p className="mt-1">Al tocar una celda de la grilla se ven los vecinos de ese horario y sus acciones.</p>
        <ul className="mt-4 space-y-2 text-xs">
          <li className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-emerald-100 bg-emerald-50" />Libre</li>
          <li className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-amber-200 bg-amber-50" />Con lugares libres</li>
          <li className="flex items-center gap-2"><span className="h-3 w-3 rounded bg-institucional-600" />Completo</li>
          <li className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-slate-200 bg-slate-50" />Ya pasó</li>
        </ul>
      </aside>
    );
  }

  const ocupan = ocupanLugar;

  return (
    <aside className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{agenda.nombre}</p>
          <h3 className="text-lg font-semibold text-slate-900">
            {etiquetaDia(seleccion.fecha)} · {seleccion.hora}
          </h3>
          <p className="text-sm text-slate-600">
            {ocupan} de {agenda.cupos_por_horario} {agenda.cupos_por_horario === 1 ? "lugar ocupado" : "lugares ocupados"}
          </p>
        </div>
        <button type="button" onClick={onCerrar} className="rounded p-1 text-slate-400 hover:text-slate-700" aria-label="Cerrar detalle">
          <X size={16} aria-hidden />
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-800">
          <p>{error}</p>
          {alternativas.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {alternativas.map((iso) => {
                const libre = enArgentina(new Date(iso));
                return (
                  <button
                    key={iso}
                    type="button"
                    onClick={() => {
                      if (moviendo) {
                        setNuevaFecha(libre.fecha);
                        setNuevaHora(libre.hora);
                      } else {
                        onElegir(libre);
                      }
                    }}
                    className="rounded-full bg-white px-2 py-0.5 font-medium text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100"
                  >
                    {etiquetaDia(libre.fecha)} · {libre.hora}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {bloqueo && (
        <p className="mt-3 flex items-center gap-1.5 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-800">
          <Ban size={13} aria-hidden /> Día sin atención: {bloqueo}
        </p>
      )}

      {hayLugar && !reservando && (
        <button
          type="button"
          onClick={() => setReservando(true)}
          className="mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-institucional-600 px-3 py-2 text-sm font-medium text-white hover:bg-institucional-700"
        >
          <CalendarPlus size={15} aria-hidden /> Reservar este horario
        </button>
      )}

      {reservando && (
        <form
          className="mt-4 space-y-2 rounded-lg border border-institucional-100 bg-institucional-50/40 p-3"
          onSubmit={(evento) => {
            evento.preventDefault();
            void ejecutar(() =>
              reservarDesdePanel(agenda.id, {
                documento: documento.trim(),
                nombre: nombre.trim(),
                fecha_hora: `${seleccion.fecha}T${seleccion.hora}`,
                canal,
              }),
            );
          }}
        >
          <p className="text-xs font-medium text-slate-700">Turno para quien llamó o se acercó a la sede</p>
          <input
            required
            inputMode="numeric"
            pattern="[0-9]{6,9}"
            value={documento}
            onChange={(evento) => setDocumento(evento.target.value)}
            placeholder="DNI, sin puntos"
            className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-institucional-500"
          />
          <input
            value={nombre}
            onChange={(evento) => setNombre(evento.target.value)}
            placeholder="Nombre y apellido (si es la primera vez)"
            className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-institucional-500"
          />
          <select
            value={canal}
            onChange={(evento) => setCanal(evento.target.value as CanalDeReserva)}
            className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
          >
            <option value="voz">Lo pidió por teléfono</option>
            <option value="whatsapp">Lo pidió por WhatsApp</option>
            <option value="email">Lo pidió por correo</option>
          </select>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={ocupado}
              className="rounded-md bg-institucional-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-institucional-700 disabled:opacity-50"
            >
              Confirmar turno
            </button>
            <button type="button" onClick={() => setReservando(false)} className="px-2.5 py-1.5 text-xs text-slate-600">
              Volver
            </button>
          </div>
        </form>
      )}

      {reservas.length === 0 && !bloqueo && (
        <p className="mt-4 text-sm text-slate-500">
          {pasado ? "Nadie tuvo turno en este horario." : "Horario libre: el agente lo ofrece cuando un vecino pide turno."}
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {reservas.map((reserva) => (
          <li key={reserva.id} className="rounded-lg border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-slate-900">{reserva.ciudadano.nombre}</p>
                <p className="text-xs text-slate-500">DNI {reserva.ciudadano.documento}</p>
                <Link to={`/casos/${reserva.caso_id}`} className="font-mono text-xs text-institucional-600 hover:underline">
                  {reserva.referencia}
                </Link>
              </div>
              <EstadoTurno estado={reserva.estado} />
            </div>
            {reserva.estado === "cancelada" && reserva.motivo_cancelacion && (
              <p className="mt-2 text-xs text-slate-500">Motivo: {reserva.motivo_cancelacion}</p>
            )}
            {reserva.recordatorio_enviado_en && reserva.estado === "confirmada" && (
              <p className="mt-2 flex items-center gap-1 text-xs text-slate-500">
                <BellRing size={12} aria-hidden /> Recordatorio enviado
              </p>
            )}

            {reserva.estado === "confirmada" && !pasado && moviendo !== reserva.id && cancelando !== reserva.id && (
              <button
                type="button"
                onClick={() => {
                  setMoviendo(reserva.id);
                  setNuevaFecha(seleccion.fecha);
                  setNuevaHora("");
                }}
                className="mt-3 mr-2 inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:border-institucional-500 hover:text-institucional-700"
              >
                <ArrowRightLeft size={13} aria-hidden /> Cambiar horario
              </button>
            )}

            {moviendo === reserva.id && (
              <div className="mt-3 space-y-2">
                <div className="flex gap-2">
                  <input
                    type="date"
                    value={nuevaFecha}
                    onChange={(evento) => {
                      setNuevaFecha(evento.target.value);
                      setNuevaHora("");
                    }}
                    className="w-1/2 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                  />
                  <select
                    value={nuevaHora}
                    onChange={(evento) => setNuevaHora(evento.target.value)}
                    className="w-1/2 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                  >
                    <option value="">Hora</option>
                    {(nuevaFecha ? horariosDelDia(agenda, nuevaFecha) : []).map((hora) => (
                      <option key={hora} value={hora}>
                        {hora}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={ocupado || !nuevaFecha || !nuevaHora}
                    onClick={() => void ejecutar(() => reprogramarReserva(reserva.id, `${nuevaFecha}T${nuevaHora}`))}
                    className="rounded-md bg-institucional-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-institucional-700 disabled:opacity-50"
                  >
                    Confirmar cambio
                  </button>
                  <button type="button" onClick={() => setMoviendo(null)} className="px-2.5 py-1.5 text-xs text-slate-600">
                    Volver
                  </button>
                </div>
                <p className="text-xs text-slate-500">El horario actual queda libre para otro vecino.</p>
              </div>
            )}

            {reserva.estado === "confirmada" && pasado && (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={ocupado}
                  onClick={() => void ejecutar(() => registrarAsistencia(reserva.id, "atendida"))}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-300 px-2.5 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50 disabled:opacity-50"
                >
                  <UserCheck size={13} aria-hidden /> Asistió
                </button>
                <button
                  type="button"
                  disabled={ocupado}
                  onClick={() => void ejecutar(() => registrarAsistencia(reserva.id, "ausente"))}
                  className="inline-flex items-center gap-1 rounded-md border border-amber-300 px-2.5 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                >
                  <UserX size={13} aria-hidden /> No asistió
                </button>
              </div>
            )}

            {reserva.estado === "confirmada" && !pasado && cancelando !== reserva.id && moviendo !== reserva.id && (
              <button
                type="button"
                onClick={() => setCancelando(reserva.id)}
                className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:border-rose-400 hover:text-rose-700"
              >
                <CalendarX size={13} aria-hidden /> Cancelar turno
              </button>
            )}

            {cancelando === reserva.id && (
              <div className="mt-3 space-y-2">
                <input
                  type="text"
                  value={motivo}
                  onChange={(evento) => setMotivo(evento.target.value)}
                  placeholder="Motivo (opcional), ej.: avisó por teléfono"
                  className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs outline-none focus:border-institucional-500"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={ocupado}
                    onClick={() => void ejecutar(() => cancelarReserva(reserva.id, motivo.trim()))}
                    className="rounded-md bg-rose-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-50"
                  >
                    Confirmar cancelación
                  </button>
                  <button
                    type="button"
                    onClick={() => setCancelando(null)}
                    className="rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900"
                  >
                    Volver
                  </button>
                </div>
                <p className="text-xs text-slate-500">El horario queda libre para otro vecino.</p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}

/**
 * Los turnos de un día de todas las agendas juntas, en orden de hora: lo que
 * necesita el mostrador para llamar a cada vecino y marcar si vino.
 */
function VistaDelDia({ hoy }: { hoy: string }) {
  const [fecha, setFecha] = useState(hoy);
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verCancelados, setVerCancelados] = useState(false);
  const [marcando, setMarcando] = useState<string | null>(null);
  const [ahora, setAhora] = useState(() => enArgentina(new Date()));

  const cargar = useCallback(async () => {
    try {
      setTurnos(await listarTurnos(fecha, 1));
      setAhora(enArgentina(new Date()));
      setError(null);
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudieron cargar los turnos");
    } finally {
      setCargando(false);
    }
  }, [fecha]);

  useEffect(() => {
    void cargar();
    const temporizador = setInterval(() => void cargar(), REFRESCO_MS);
    return () => clearInterval(temporizador);
  }, [cargar]);

  const filas = useMemo(
    () =>
      turnos
        .flatMap((agenda) => agenda.reservas.map((reserva) => ({ reserva, agenda })))
        .sort(
          (a, b) => new Date(a.reserva.fecha_hora).getTime() - new Date(b.reserva.fecha_hora).getTime(),
        ),
    [turnos],
  );
  const vigentes = filas.filter((f) => f.reserva.estado !== "cancelada");
  const cancelados = filas.length - vigentes.length;
  const visibles = verCancelados ? filas : vigentes;
  const cuenta = (estado: EstadoReserva) => vigentes.filter((f) => f.reserva.estado === estado).length;
  const bloqueos = turnos.flatMap((agenda) =>
    agenda.bloqueos.filter((b) => b.fecha === fecha).map((b) => ({ agenda, motivo: b.motivo })),
  );

  // El próximo a llamar: el primer turno confirmado de hoy que todavía no pasó.
  const ahoraClave = `${ahora.fecha} ${ahora.hora}`;
  const proximo =
    fecha === hoy
      ? vigentes.find((f) => {
          const { fecha: dia, hora } = enArgentina(new Date(f.reserva.fecha_hora));
          return f.reserva.estado === "confirmada" && `${dia} ${hora}` >= ahoraClave;
        })?.reserva.id
      : undefined;

  async function marcar(reserva: Reserva, estado: "atendida" | "ausente") {
    setMarcando(reserva.id);
    try {
      await registrarAsistencia(reserva.id, estado);
      await cargar();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo registrar la asistencia");
    } finally {
      setMarcando(null);
    }
  }

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => setFecha(sumarDias(fecha, -1))}
          className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:border-institucional-500"
          aria-label="Día anterior"
        >
          <ChevronLeft size={16} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setFecha(hoy)}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:border-institucional-500"
        >
          Hoy
        </button>
        <button
          type="button"
          onClick={() => setFecha(sumarDias(fecha, 1))}
          className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:border-institucional-500"
          aria-label="Día siguiente"
        >
          <ChevronRight size={16} aria-hidden />
        </button>
        <h3 className="ml-2 text-lg font-semibold text-slate-900">
          {etiquetaDiaLarga(fecha)}
          {fecha === hoy && (
            <span className="ml-2 rounded bg-institucional-600 px-1.5 py-0.5 align-middle text-xs font-medium text-white">
              hoy
            </span>
          )}
        </h3>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Indicador icono={CalendarClock} etiqueta="Turnos del día" valor={String(vigentes.length)} detalle="Todas las agendas" />
        <Indicador icono={Clock} etiqueta="Por atender" valor={String(cuenta("confirmada"))} detalle="Confirmados sin marcar" />
        <Indicador icono={UserCheck} etiqueta="Atendidos" valor={String(cuenta("atendida"))} detalle="Vinieron" />
        <Indicador icono={UserX} etiqueta="Ausentes" valor={String(cuenta("ausente"))} detalle="No vinieron" />
      </div>

      {bloqueos.map(({ agenda, motivo }) => (
        <p
          key={agenda.id}
          className="mb-3 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800"
        >
          <Ban size={15} aria-hidden />
          {agenda.nombre}: sin atención este día ({motivo}).
        </p>
      ))}

      {error && (
        <p className="mb-3 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {cargando ? (
          <p className="px-5 py-8 text-sm text-slate-500">Cargando turnos…</p>
        ) : visibles.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-slate-500">No hay turnos dados para este día.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {visibles.map(({ reserva, agenda }) => {
              const { hora } = enArgentina(new Date(reserva.fecha_hora));
              const esProximo = reserva.id === proximo;
              return (
                <li
                  key={reserva.id}
                  className={`flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 ${
                    esProximo ? "bg-institucional-50" : reserva.estado === "cancelada" ? "opacity-60" : ""
                  }`}
                >
                  <div className="w-16 shrink-0">
                    <div className="text-lg font-semibold tabular-nums text-slate-900">{hora}</div>
                    {esProximo && (
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-institucional-700">
                        Próximo
                      </span>
                    )}
                  </div>
                  <div className="min-w-44 flex-1">
                    <div className="font-medium text-slate-900">{reserva.ciudadano.nombre}</div>
                    <div className="text-xs text-slate-500">DNI {reserva.ciudadano.documento}</div>
                  </div>
                  <div className="min-w-44 flex-1 text-sm text-slate-700">
                    <div>{agenda.nombre}</div>
                    {agenda.sede && (
                      <div className="flex items-center gap-1 text-xs text-slate-500">
                        <MapPin size={12} aria-hidden />
                        {agenda.sede}
                      </div>
                    )}
                  </div>
                  <Link
                    to={`/casos/${reserva.caso_id}`}
                    className="font-mono text-xs text-institucional-600 hover:underline"
                  >
                    {reserva.referencia}
                  </Link>
                  <div className="flex w-56 items-center justify-end gap-2">
                    {reserva.estado === "confirmada" && fecha <= hoy ? (
                      <>
                        <button
                          type="button"
                          disabled={marcando !== null}
                          onClick={() => void marcar(reserva, "atendida")}
                          className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 active:translate-y-px disabled:opacity-50"
                        >
                          <UserCheck size={14} aria-hidden />
                          Vino
                        </button>
                        <button
                          type="button"
                          disabled={marcando !== null}
                          onClick={() => void marcar(reserva, "ausente")}
                          className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:border-amber-500 hover:text-amber-800 active:translate-y-px disabled:opacity-50"
                        >
                          <UserX size={14} aria-hidden />
                          No vino
                        </button>
                      </>
                    ) : (
                      <EstadoTurno estado={reserva.estado} />
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {cancelados > 0 && (
        <button
          type="button"
          onClick={() => setVerCancelados((valor) => !valor)}
          className="mt-3 text-sm text-institucional-600 hover:underline"
        >
          {verCancelados
            ? "Ocultar los cancelados"
            : `Ver ${cancelados === 1 ? "el turno cancelado" : `los ${cancelados} turnos cancelados`}`}
        </button>
      )}
    </section>
  );
}
