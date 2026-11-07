import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, Archive, Download, Inbox, Search, UserRound } from "lucide-react";

import { useAuth } from "../auth";
import { EstadoBadge, RecorridoCanal, TipoBadge } from "../componentes/Etiquetas";
import { Espera } from "../componentes/Espera";
import { Pestanas } from "../componentes/Pestanas";
import { contarCasos, exportarCasos, listarCasos } from "../lib/casos";
import { formatearFechaHora, idCorto } from "../lib/formato";
import { ESTADOS_ACTIVOS, ETIQUETA_ESTADO, type Caso, type EstadoCaso } from "../lib/tipos";

type Filtro = EstadoCaso | "todos";
type Solapa = "casos" | "archivados";

const POR_PAGINA = 20;
const REFRESCO_MS = 20_000;

export function ListaCasos() {
  const navegar = useNavigate();
  const { usuario } = useAuth();
  const esSupervisor = usuario?.rol === "supervisor";

  const [casos, setCasos] = useState<Caso[]>([]);
  const [total, setTotal] = useState(0);
  const [conteos, setConteos] = useState<Record<string, number>>({});
  const [solapa, setSolapa] = useState<Solapa>("casos");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [sinAsignar, setSinAsignar] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  const [pagina, setPagina] = useState(0);
  const [cargando, setCargando] = useState(true);
  const [refrescando, setRefrescando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Los contadores de los filtros salen de /api/casos/conteos, que aplica la
  // misma visibilidad por rol que la lista: con la lista paginada, contarlos
  // en memoria daría números falsos.
  const primeraCarga = useRef(true);

  const cargar = useCallback(async () => {
    if (primeraCarga.current) {
      setCargando(true);
    } else {
      setRefrescando(true);
    }
    try {
      const [pagina_, conteo] = await Promise.all([
        listarCasos({
          estado: solapa === "casos" && filtro !== "todos" ? filtro : undefined,
          archivados: solapa === "archivados",
          q: busqueda.trim() || undefined,
          sinAsignar: solapa === "casos" && sinAsignar && esSupervisor,
          limite: POR_PAGINA,
          desplazamiento: pagina * POR_PAGINA,
        }),
        contarCasos().catch(() => null),
      ]);
      setCasos(pagina_.datos);
      setTotal(pagina_.total);
      if (conteo) {
        setConteos({ todos: conteo.todos, ...conteo.por_estado });
      }
      setError(null);
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudieron cargar los casos");
    } finally {
      primeraCarga.current = false;
      setCargando(false);
      setRefrescando(false);
    }
  }, [solapa, filtro, busqueda, sinAsignar, pagina, esSupervisor]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  useEffect(() => {
    // Un caso entrante aparece solo, sin que el operador tenga que recargar.
    const temporizador = setInterval(() => void cargar(), REFRESCO_MS);
    return () => clearInterval(temporizador);
  }, [cargar]);

  function cambiarFiltro(nuevo: Filtro) {
    setFiltro(nuevo);
    setPagina(0);
  }

  function cambiarSolapa(nueva: Solapa) {
    setSolapa(nueva);
    setFiltro("todos");
    setSinAsignar(false);
    setPagina(0);
  }

  const ultimaPagina = Math.max(Math.ceil(total / POR_PAGINA) - 1, 0);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            {esSupervisor ? "Casos del organismo" : "Mi bandeja"}
            {solapa === "archivados" && " · Archivados"}
          </h2>
          <p className="text-sm text-slate-600">
            {cargando ? "Cargando casos…" : `${total} caso(s)`}
            {!esSupervisor && solapa === "casos" && " asignados a usted"}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <label className="relative">
            <span className="sr-only">Buscar por nombre o documento</span>
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              aria-hidden
            />
            <input
              type="search"
              value={busqueda}
              onChange={(evento) => {
                setBusqueda(evento.target.value);
                setPagina(0);
              }}
              placeholder="Buscar por nombre o DNI"
              className="w-72 rounded-md border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100"
            />
          </label>

          {esSupervisor && (
            <button
              type="button"
              onClick={() => void exportarCasos()}
              className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-institucional-500 hover:text-institucional-700 active:translate-y-px"
            >
              <Download size={15} aria-hidden />
              Exportar
            </button>
          )}
        </div>
      </div>

      <div className="mb-4">
        <Pestanas
          pestanas={[
            { id: "casos", etiqueta: "Casos", contador: conteos.todos },
            { id: "archivados", etiqueta: "Archivados", contador: conteos.cerrado ?? 0 },
          ]}
          activa={solapa}
          onCambiar={(id) => cambiarSolapa(id as Solapa)}
          etiquetaAria="Bandeja activa o archivo de casos cerrados"
        />
      </div>

      {solapa === "casos" && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {(["todos", ...ESTADOS_ACTIVOS] as Filtro[]).map((opcion) => (
            <button
              key={opcion}
              type="button"
              onClick={() => cambiarFiltro(opcion)}
              aria-pressed={filtro === opcion}
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition ${
                filtro === opcion
                  ? "bg-institucional-600 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {opcion === "todos" ? "Todos" : ETIQUETA_ESTADO[opcion]}
              {conteos[opcion] !== undefined && (
                <span
                  className={`rounded-full px-1.5 text-xs tabular-nums ${
                    filtro === opcion ? "bg-institucional-700" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {conteos[opcion]}
                </span>
              )}
            </button>
          ))}

          {esSupervisor && (
            <button
              type="button"
              onClick={() => {
                setSinAsignar((valor) => !valor);
                setPagina(0);
              }}
              aria-pressed={sinAsignar}
              className={`ml-2 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition ${
                sinAsignar
                  ? "bg-amber-500 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              Sin asignar
            </button>
          )}
        </div>
      )}

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      {/* Al refrescar se atenúa la tabla en vez de mostrar el esqueleto: sin salto de layout. */}
      <div
        className={`overflow-hidden rounded-lg border border-slate-300 bg-white transition-opacity ${
          refrescando ? "opacity-60" : "opacity-100"
        }`}
      >
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-4 py-2.5 font-semibold">Caso</th>
              <th className="px-4 py-2.5 font-semibold">Título</th>
              <th className="px-4 py-2.5 font-semibold">Ciudadano</th>
              <th className="px-4 py-2.5 font-semibold">Tipo</th>
              <th className="px-4 py-2.5 font-semibold">Estado</th>
              <th className="px-4 py-2.5 font-semibold">Canal</th>
              <th className="px-4 py-2.5 font-semibold">Esperando</th>
              {esSupervisor && <th className="px-4 py-2.5 font-semibold">Asignado</th>}
              <th className="px-4 py-2.5 font-semibold">Actualizado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {cargando &&
              [0, 1, 2, 3].map((fila) => (
                <tr key={fila}>
                  <td colSpan={esSupervisor ? 9 : 8} className="px-4 py-3">
                    <div className="h-5 animate-pulse rounded bg-slate-100" />
                  </td>
                </tr>
              ))}

            {!cargando &&
              casos.map((caso) => (
                <tr
                  key={caso.id}
                  onClick={() => navegar(`/casos/${caso.id}`)}
                  className="cursor-pointer transition hover:bg-institucional-50"
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500">
                    {idCorto(caso.id)}
                  </td>
                  <td className="min-w-64 max-w-md px-4 py-2.5">
                    {caso.titulo ? (
                      <span className="block truncate text-slate-800" title={caso.titulo}>
                        {caso.titulo}
                      </span>
                    ) : (
                      <span className="italic text-slate-400">Sin título</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-900">{caso.ciudadano.nombre}</div>
                    <div className="text-xs text-slate-500">DNI {caso.ciudadano.documento}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <TipoBadge tipo={caso.tipo} />
                  </td>
                  <td className="px-4 py-2.5">
                    <EstadoBadge estado={caso.estado} />
                  </td>
                  <td className="px-4 py-2.5">
                    <RecorridoCanal origen={caso.canal_origen} actual={caso.canal_actual} />
                  </td>
                  <td className="px-4 py-2.5">
                    <Espera desde={caso.esperando_desde} />
                  </td>
                  {esSupervisor && (
                    <td className="px-4 py-2.5">
                      {caso.operador_asignado ? (
                        <span className="inline-flex items-center gap-1.5 text-slate-700">
                          <UserRound size={14} className="text-slate-400" aria-hidden />
                          {caso.operador_asignado.nombre}
                        </span>
                      ) : (
                        <span className="text-slate-400">Sin asignar</span>
                      )}
                    </td>
                  )}
                  <td className="px-4 py-2.5 text-slate-600">
                    {formatearFechaHora(caso.updated_at)}
                  </td>
                </tr>
              ))}

            {!cargando && casos.length === 0 && (
              <tr>
                <td colSpan={esSupervisor ? 9 : 8} className="px-4 py-12 text-center">
                  {solapa === "archivados" ? (
                    <>
                      <Archive size={28} className="mx-auto mb-2 text-slate-300" aria-hidden />
                      <p className="text-slate-600">Todavía no hay casos cerrados que archivar.</p>
                    </>
                  ) : (
                    <>
                      <Inbox size={28} className="mx-auto mb-2 text-slate-300" aria-hidden />
                      <p className="text-slate-600">
                        {esSupervisor
                          ? "Ningún caso coincide con el filtro o la búsqueda."
                          : "No tiene casos asignados. Un supervisor se los va a asignar."}
                      </p>
                    </>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {ultimaPagina > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-slate-600">
            Página {pagina + 1} de {ultimaPagina + 1}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pagina === 0}
              onClick={() => setPagina((valor) => valor - 1)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 transition hover:border-institucional-500 disabled:opacity-50"
            >
              Anterior
            </button>
            <button
              type="button"
              disabled={pagina >= ultimaPagina}
              onClick={() => setPagina((valor) => valor + 1)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 transition hover:border-institucional-500 disabled:opacity-50"
            >
              Siguiente
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
