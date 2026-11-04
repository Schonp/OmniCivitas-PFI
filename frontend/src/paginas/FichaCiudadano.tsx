import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, ArrowRight, Lock, Sparkles, UserRound } from "lucide-react";

import { CanalBadge, EstadoBadge, TipoBadge } from "../componentes/Etiquetas";
import { obtenerFicha } from "../lib/ciudadanos";
import { formatearFechaHora } from "../lib/formato";
import { ETIQUETA_ACTOR, type CasoEnFicha, type FichaCiudadano as Ficha } from "../lib/tipos";

function Dato({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{etiqueta}</dt>
      <dd className="mt-0.5 text-sm font-medium text-slate-900">{valor}</dd>
    </div>
  );
}

function Recorrido({ canales }: { canales: CasoEnFicha["recorrido"] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {canales.map((canal, indice) => (
        <span key={canal} className="inline-flex items-center gap-1">
          {indice > 0 && <ArrowRight size={12} className="text-slate-400" aria-label="después por" />}
          <CanalBadge canal={canal} />
        </span>
      ))}
    </span>
  );
}

function TarjetaCaso({ caso }: { caso: CasoEnFicha }) {
  const cambioDeCanal = caso.recorrido.length > 1;
  return (
    <li className="relative pl-8">
      {/* El punto de la línea de tiempo: lleno si el caso sigue en curso. */}
      <span
        className={`absolute left-0 top-5 h-3.5 w-3.5 rounded-full ring-4 ring-slate-50 ${
          caso.estado === "cerrado" ? "bg-slate-300" : "bg-institucional-600"
        }`}
        aria-hidden
      />
      <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <TipoBadge tipo={caso.tipo} />
              <EstadoBadge estado={caso.estado} />
              <span className="font-mono text-xs text-slate-500">{caso.referencia}</span>
            </div>
            <p className="mt-1.5 text-xs text-slate-500">
              Abierto el {formatearFechaHora(caso.created_at)} · {caso.mensajes}{" "}
              {caso.mensajes === 1 ? "mensaje" : "mensajes"}
            </p>
          </div>
          {caso.puede_abrir ? (
            <Link
              to={`/casos/${caso.id}`}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:border-institucional-500 hover:text-institucional-700"
            >
              Abrir caso
              <ArrowRight size={14} aria-hidden />
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs text-slate-500">
              <Lock size={13} aria-hidden />
              Lo atiende otra persona
            </span>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-600">
          {caso.recorrido.length > 0 ? (
            <span className="flex items-center gap-1.5">
              <span className="text-slate-500">{cambioDeCanal ? "Pasó por:" : "Canal:"}</span>
              <Recorrido canales={caso.recorrido} />
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <span className="text-slate-500">Canal:</span>
              <CanalBadge canal={caso.canal_origen} />
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <UserRound size={14} className="text-slate-400" aria-hidden />
            {caso.operador_asignado ? caso.operador_asignado.nombre : "Lo atiende el asistente virtual"}
          </span>
        </div>

        {caso.resumen_ia && (
          <p className="mt-3 flex gap-2 rounded-md bg-institucional-50 px-3 py-2 text-sm text-slate-800">
            <Sparkles size={15} className="mt-0.5 shrink-0 text-institucional-600" aria-hidden />
            {caso.resumen_ia}
          </p>
        )}

        {caso.ultimo_mensaje && (
          <div className="mt-3 border-t border-slate-100 pt-3 text-sm">
            <p className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              Último mensaje · {ETIQUETA_ACTOR[caso.ultimo_mensaje.actor]}
              <CanalBadge canal={caso.ultimo_mensaje.canal} />
              {formatearFechaHora(caso.ultimo_mensaje.timestamp)}
            </p>
            <p className="mt-1 line-clamp-2 text-slate-700">{caso.ultimo_mensaje.contenido}</p>
          </div>
        )}
      </article>
    </li>
  );
}

export function FichaCiudadano() {
  const { ciudadanoId = "" } = useParams();
  const navigate = useNavigate();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    obtenerFicha(ciudadanoId)
      .then((datos) => {
        setFicha(datos);
        setError(null);
      })
      .catch((excepcion) =>
        setError(excepcion instanceof Error ? excepcion.message : "No se pudo cargar la ficha"),
      );
  }, [ciudadanoId]);

  const volver = (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="inline-flex items-center gap-1.5 text-sm text-institucional-600 hover:underline"
    >
      <ArrowLeft size={15} aria-hidden />
      Volver
    </button>
  );

  if (error) {
    return (
      <div>
        {volver}
        <p className="mt-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      </div>
    );
  }
  if (ficha === null) {
    return <p className="text-slate-500">Cargando ficha…</p>;
  }

  const enCurso = ficha.casos.filter((caso) => caso.estado !== "cerrado").length;

  return (
    <div>
      {volver}

      <section className="mt-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Ficha del vecino</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{ficha.nombre}</h2>
        <p className="mt-1 text-sm text-slate-600">
          {ficha.identificado ? `DNI ${ficha.documento}` : "Todavía no se identificó con su DNI"}
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">Se comunicó por:</span>
          {ficha.canales.length > 0 ? (
            ficha.canales.map((canal) => <CanalBadge key={canal} canal={canal} />)
          ) : (
            <span className="text-slate-500">sin mensajes todavía</span>
          )}
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 sm:grid-cols-4">
          <Dato etiqueta="Casos" valor={String(ficha.casos.length)} />
          <Dato etiqueta="En curso" valor={String(enCurso)} />
          <Dato
            etiqueta="Primer contacto"
            valor={ficha.primer_contacto ? formatearFechaHora(ficha.primer_contacto) : "—"}
          />
          <Dato
            etiqueta="Último mensaje"
            valor={ficha.ultimo_contacto ? formatearFechaHora(ficha.ultimo_contacto) : "—"}
          />
        </dl>
      </section>

      <h3 className="mb-3 mt-8 text-sm font-semibold text-slate-900">
        Historia de sus casos, del más reciente al más antiguo
      </h3>
      {ficha.casos.length > 0 ? (
        <ol className="relative space-y-4 before:absolute before:bottom-4 before:left-[6px] before:top-4 before:w-0.5 before:bg-slate-200">
          {ficha.casos.map((caso) => (
            <TarjetaCaso key={caso.id} caso={caso} />
          ))}
        </ol>
      ) : (
        <p className="rounded-lg border border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
          No tiene casos registrados.
        </p>
      )}
    </div>
  );
}
