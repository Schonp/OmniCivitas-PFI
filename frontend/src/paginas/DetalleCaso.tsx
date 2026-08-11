import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  EyeOff,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { useAuth } from "../auth";
import { CanalBadge, EstadoBadge, RecorridoCanal, TipoBadge } from "../componentes/Etiquetas";
import { PanelPestana, Pestanas } from "../componentes/Pestanas";
import {
  asignarCaso,
  cambiarEstadoCaso,
  generarResumenCaso,
  listarAuditoria,
  listarInteracciones,
  listarUsuarios,
  obtenerCaso,
  responderCaso,
} from "../lib/casos";
import { formatearFechaHora, formatearHora, idCorto } from "../lib/formato";
import {
  ESTADOS,
  ETIQUETA_ACTOR,
  ETIQUETA_ESTADO,
  ETIQUETA_MOTIVO,
  MOTIVOS_CIERRE,
  type Auditoria,
  type Caso,
  type EstadoCaso,
  type Interaccion,
  type MotivoCierre,
  type Usuario,
} from "../lib/tipos";

function valorAuditoria(valor: unknown): string {
  if (valor === null || valor === undefined) {
    return "—";
  }
  if (typeof valor === "boolean") {
    return valor ? "sí" : "no";
  }
  return String(valor);
}

const ESTILO_BURBUJA = {
  ciudadano: "bg-white ring-1 ring-slate-200 text-slate-800",
  agente_ia: "bg-institucional-600 text-white",
  operador: "bg-amber-100 ring-1 ring-amber-300 text-amber-950",
} as const;

export function DetalleCaso() {
  const { casoId = "" } = useParams();
  const { usuario } = useAuth();

  const [caso, setCaso] = useState<Caso | null>(null);
  const [interacciones, setInteracciones] = useState<Interaccion[]>([]);
  const [auditoria, setAuditoria] = useState<Auditoria[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [respuesta, setRespuesta] = useState("");
  const [pestana, setPestana] = useState("conversacion");
  const [motivo, setMotivo] = useState<MotivoCierre | "">("");
  const [notaInterna, setNotaInterna] = useState(false);
  const [equipo, setEquipo] = useState<Usuario[]>([]);
  const [generandoResumen, setGenerandoResumen] = useState(false);

  const esSupervisor = usuario?.rol === "supervisor";

  useEffect(() => {
    if (!esSupervisor) {
      return;
    }
    listarUsuarios()
      .then(setEquipo)
      .catch(() => setEquipo([]));
  }, [esSupervisor]);

  const cargar = useCallback(async () => {
    try {
      const [detalle, mensajes, registros] = await Promise.all([
        obtenerCaso(casoId),
        listarInteracciones(casoId),
        listarAuditoria(casoId),
      ]);
      setCaso(detalle);
      setInteracciones(mensajes);
      setAuditoria(registros);
      setError(null);
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo cargar el caso");
    }
  }, [casoId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function ejecutar(accion: () => Promise<unknown>) {
    setGuardando(true);
    try {
      await accion();
      await cargar();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo completar la acción");
    } finally {
      setGuardando(false);
    }
  }

  async function generarResumen() {
    setGenerandoResumen(true);
    try {
      await generarResumenCaso(casoId);
      // Recarga completa: el resumen también deja su registro de auditoría.
      await cargar();
    } catch (excepcion) {
      setError(
        excepcion instanceof Error ? excepcion.message : "No se pudo generar el resumen",
      );
    } finally {
      setGenerandoResumen(false);
    }
  }

  async function enviarRespuesta(evento: FormEvent) {
    evento.preventDefault();
    const contenido = respuesta.trim();
    if (contenido === "") {
      return;
    }
    await ejecutar(async () => {
      await responderCaso(casoId, contenido, notaInterna);
      setRespuesta("");
    });
  }

  if (error && caso === null) {
    return (
      <p className="flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
        <AlertCircle size={16} aria-hidden />
        {error}
      </p>
    );
  }
  if (caso === null) {
    return <p className="text-slate-500">Cargando caso…</p>;
  }

  const cerrado = caso.estado === "cerrado";

  return (
    <div>
      <Link
        to="/casos"
        className="inline-flex items-center gap-1.5 text-sm text-institucional-600 hover:underline"
      >
        <ArrowLeft size={15} aria-hidden />
        Volver a casos
      </Link>

      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                {caso.ciudadano.nombre}
              </h2>
              <EstadoBadge estado={caso.estado} />
              <TipoBadge tipo={caso.tipo} />
            </div>

            <p className="mt-2 text-sm text-slate-600">
              DNI {caso.ciudadano.documento} · Caso{" "}
              <span className="font-mono">{idCorto(caso.id)}</span> · Abierto el{" "}
              {formatearFechaHora(caso.created_at)}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
              <span className="flex items-center gap-1.5">
                <span className="text-slate-500">Canal:</span>
                <RecorridoCanal origen={caso.canal_origen} actual={caso.canal_actual} />
              </span>
              <span className="flex items-center gap-1.5 text-slate-600">
                <UserRound size={15} className="text-slate-400" aria-hidden />
                {caso.operador_asignado ? caso.operador_asignado.nombre : "Sin asignar"}
              </span>
            </div>
          </div>

          <div className="flex w-full max-w-xs flex-col items-stretch gap-3">
            {esSupervisor && (
              <label className="text-sm">
                <span className="mb-1 block font-medium text-slate-700">Asignar a</span>
                <select
                  value={caso.operador_asignado?.id ?? ""}
                  disabled={guardando}
                  onChange={(evento) =>
                    void ejecutar(() => asignarCaso(casoId, evento.target.value || null))
                  }
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100"
                >
                  <option value="">Sin asignar</option>
                  {equipo.map((integrante) => (
                    <option key={integrante.id} value={integrante.id}>
                      {integrante.nombre} ({integrante.rol})
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="flex flex-wrap gap-2">
              {ESTADOS.filter((estado) => estado !== caso.estado && estado !== "cerrado").map(
                (estado) => (
                  <button
                    key={estado}
                    type="button"
                    disabled={guardando}
                    onClick={() => void ejecutar(() => cambiarEstadoCaso(casoId, estado))}
                    className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:border-institucional-500 hover:text-institucional-700 active:translate-y-px disabled:opacity-60"
                  >
                    {ETIQUETA_ESTADO[estado as EstadoCaso]}
                  </button>
                ),
              )}
            </div>

            {!cerrado && (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <label
                  htmlFor="motivo-cierre"
                  className="block text-sm font-medium text-slate-700"
                >
                  Cerrar el caso
                </label>
                <select
                  id="motivo-cierre"
                  value={motivo}
                  onChange={(evento) => setMotivo(evento.target.value as MotivoCierre | "")}
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100"
                >
                  <option value="">Elija el motivo…</option>
                  {MOTIVOS_CIERRE.map((opcion) => (
                    <option key={opcion} value={opcion}>
                      {ETIQUETA_MOTIVO[opcion]}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={guardando || motivo === ""}
                  onClick={() =>
                    void ejecutar(() =>
                      cambiarEstadoCaso(casoId, "cerrado", motivo as MotivoCierre),
                    )
                  }
                  className="mt-2 w-full rounded-md bg-institucional-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-institucional-700 active:translate-y-px disabled:opacity-50"
                >
                  Cerrar caso
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-institucional-100 bg-institucional-50 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-institucional-900">
            <Sparkles size={16} className="text-institucional-600" aria-hidden />
            Resumen del caso (IA)
          </h3>
          <button
            type="button"
            disabled={generandoResumen || interacciones.length === 0}
            onClick={() => void generarResumen()}
            className="inline-flex items-center gap-2 rounded-md border border-institucional-200 bg-white px-3 py-1.5 text-sm font-medium text-institucional-700 transition hover:border-institucional-500 active:translate-y-px disabled:opacity-50"
          >
            <RefreshCw
              size={14}
              className={generandoResumen ? "animate-spin" : ""}
              aria-hidden
            />
            {generandoResumen
              ? "Generando…"
              : caso.resumen_ia
                ? "Actualizar resumen"
                : "Generar resumen"}
          </button>
        </div>

        {caso.resumen_ia ? (
          <>
            <p className="mt-3 text-sm leading-relaxed text-slate-800">{caso.resumen_ia}</p>
            {caso.resumen_ia_generado_en && (
              <p className="mt-2 text-xs text-slate-500">
                Generado el {formatearFechaHora(caso.resumen_ia_generado_en)}. Revise el
                contenido: es un resumen automático.
              </p>
            )}
          </>
        ) : (
          <p className="mt-3 text-sm text-slate-600">
            {interacciones.length === 0
              ? "El caso todavía no tiene interacciones para resumir."
              : "Todavía no se generó un resumen de este caso."}
          </p>
        )}
      </div>

      {error && (
        <p className="mt-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      <div className="mt-6">
        <Pestanas
          pestanas={[
            { id: "conversacion", etiqueta: "Conversación", contador: interacciones.length },
            { id: "auditoria", etiqueta: "Auditoría", contador: auditoria.length },
          ]}
          activa={pestana}
          onCambiar={setPestana}
          etiquetaAria="Secciones del caso"
        />

        <PanelPestana id="conversacion" activa={pestana}>
          <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-5">
            {interacciones.map((interaccion) => (
              <div
                key={interaccion.id}
                className={`flex ${interaccion.actor === "ciudadano" ? "justify-start" : "justify-end"}`}
              >
                <div className="max-w-lg">
                  <div
                    className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      interaccion.interna
                        ? "border border-dashed border-slate-400 bg-slate-100 text-slate-700"
                        : ESTILO_BURBUJA[interaccion.actor]
                    }`}
                  >
                    {interaccion.contenido}
                  </div>
                  <div
                    className={`mt-1.5 flex items-center gap-2 text-xs text-slate-500 ${
                      interaccion.actor === "ciudadano" ? "" : "justify-end"
                    }`}
                  >
                    <span>{ETIQUETA_ACTOR[interaccion.actor]}</span>
                    {interaccion.interna ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-200 px-1.5 py-0.5 font-medium text-slate-700">
                        <EyeOff size={11} aria-hidden />
                        Nota interna
                      </span>
                    ) : (
                      <CanalBadge canal={interaccion.canal} />
                    )}
                    <span>{formatearHora(interaccion.timestamp)}</span>
                  </div>
                </div>
              </div>
            ))}

            {interacciones.length === 0 && (
              <p className="py-8 text-center text-sm text-slate-500">
                Todavía no hay interacciones en este caso.
              </p>
            )}
          </div>

          <form onSubmit={enviarRespuesta} className="mt-4">
            <label htmlFor="respuesta" className="block text-sm font-medium text-slate-700">
              {notaInterna ? "Nota interna" : "Responder al ciudadano"}
            </label>
            <textarea
              id="respuesta"
              rows={3}
              maxLength={2000}
              value={respuesta}
              disabled={(cerrado && !notaInterna) || guardando}
              onChange={(evento) => setRespuesta(evento.target.value)}
              placeholder={
                notaInterna
                  ? "Queda registrada en el caso. El ciudadano nunca la ve."
                  : cerrado
                    ? "El caso está cerrado. Reabralo para poder responder."
                    : "Escriba la respuesta. Se registra sobre el canal en el que el ciudadano está conversando."
              }
              className={`mt-1 w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-institucional-100 disabled:bg-slate-100 ${
                notaInterna
                  ? "border-dashed border-slate-400 bg-slate-50"
                  : "border-slate-300 focus:border-institucional-500"
              }`}
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={notaInterna}
                  onChange={(evento) => setNotaInterna(evento.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-institucional-600 focus:ring-institucional-500"
                />
                Nota interna (el ciudadano no la ve)
              </label>

              <div className="flex items-center gap-3">
                {!notaInterna && (
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    Se enviará por
                    <CanalBadge canal={caso.canal_actual} />
                  </span>
                )}
                <button
                  type="submit"
                  disabled={(cerrado && !notaInterna) || guardando || respuesta.trim() === ""}
                  className="inline-flex items-center gap-2 rounded-md bg-institucional-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-institucional-700 active:translate-y-px disabled:opacity-50"
                >
                  {notaInterna ? <EyeOff size={15} aria-hidden /> : <Send size={15} aria-hidden />}
                  {guardando ? "Guardando…" : notaInterna ? "Guardar nota" : "Enviar respuesta"}
                </button>
              </div>
            </div>
          </form>
        </PanelPestana>

        <PanelPestana id="auditoria" activa={pestana}>
          <p className="mb-3 flex items-center gap-2 text-sm text-slate-600">
            <ShieldCheck size={15} className="text-slate-400" aria-hidden />
            Toda acción sobre el caso queda registrada: quién la hizo, cuándo y con qué datos.
          </p>

          <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Acción</th>
                  <th className="px-4 py-2.5 font-semibold">Actor</th>
                  <th className="px-4 py-2.5 font-semibold">Fecha y hora</th>
                  <th className="px-4 py-2.5 font-semibold">Detalle</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {auditoria.map((registro) => (
                  <tr key={registro.id}>
                    <td className="px-4 py-2.5 font-medium text-slate-800">{registro.accion}</td>
                    <td className="px-4 py-2.5 text-slate-600">{registro.actor}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-slate-600">
                      {formatearFechaHora(registro.timestamp)}
                    </td>
                    <td className="px-4 py-2.5">
                      {registro.metadata ? (
                        <div className="flex flex-wrap gap-1.5">
                          {Object.entries(registro.metadata).map(([clave, valor]) => (
                            <span
                              key={clave}
                              className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700"
                            >
                              {clave}: {valorAuditoria(valor)}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}

                {auditoria.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-slate-500">
                      Sin registros de auditoría.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </PanelPestana>
      </div>
    </div>
  );
}
