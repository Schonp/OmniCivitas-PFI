import { useEffect, useMemo, useRef, useState } from "react";
import { AlarmClock, BotMessageSquare, Gauge, Repeat2, Timer } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "../auth";
import { obtenerMetricas, type Metricas as DatosMetricas } from "../lib/metricas";
import {
  ESTADOS,
  ETIQUETA_CANAL,
  ETIQUETA_ESTADO,
  ETIQUETA_TIPO,
  type Canal,
  type EstadoCaso,
  type TipoCaso,
} from "../lib/tipos";

// Paleta de marcas validada con el validador del skill dataviz (superficie blanca):
// contraste, banda de luminosidad, separación CVD y piso de visión normal en PASS.
const COLOR_SERIE = "#2b6cb0"; // institucional-500
const COLOR_OPERADOR = "#d97706"; // amber-600

const porcentaje = new Intl.NumberFormat("es-AR", { style: "percent", maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 });
const dosDecimales = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2 });

const plural = (cantidad: number, singular: string, plural: string) =>
  `${cantidad} ${cantidad === 1 ? singular : plural}`;

interface TarjetaProps {
  icono: LucideIcon;
  etiqueta: string;
  valor: string;
  detalle: string;
  alerta?: boolean;
}

function Tarjeta({ icono: Icono, etiqueta, valor, detalle, alerta = false }: TarjetaProps) {
  return (
    <div
      className={`rounded-lg border bg-white p-4 ${
        alerta ? "border-rose-300 ring-1 ring-rose-100" : "border-slate-200"
      }`}
    >
      <div className="flex items-center gap-2 text-sm text-slate-600">
        <Icono size={15} className={alerta ? "text-rose-500" : "text-slate-400"} aria-hidden />
        {etiqueta}
      </div>
      {/* Figuras proporcionales: tabular-nums afloja un número grande aislado. */}
      <div className="mt-1.5 text-3xl font-semibold text-slate-900">{valor}</div>
      <div className="mt-0.5 text-xs text-slate-500">{detalle}</div>
    </div>
  );
}

interface BarrasProps {
  titulo: string;
  subtitulo: string;
  datos: Record<string, number>;
  etiquetas: Record<string, string>;
  /** Orden fijo de las filas (ej. el pipeline de estados). Sin esto, ordena por valor. */
  orden?: string[];
}

function Barras({ titulo, subtitulo, datos, etiquetas, orden }: BarrasProps) {
  const filas = orden
    ? orden.map((clave): [string, number] => [clave, datos[clave] ?? 0])
    : Object.entries(datos).sort(([, a], [, b]) => b - a);
  const maximo = Math.max(...filas.map(([, valor]) => valor), 1);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-semibold text-slate-800">{titulo}</h3>
      <p className="mt-0.5 text-xs text-slate-500">{subtitulo}</p>

      <div className="mt-4 space-y-3">
        {filas.map(([clave, valor]) => (
          <div
            key={clave}
            className="grid grid-cols-[6.5rem_1fr_2rem] items-center gap-3"
            title={`${etiquetas[clave] ?? clave}: ${valor}`}
          >
            <span className="truncate text-sm text-slate-600">{etiquetas[clave] ?? clave}</span>
            <div className="h-2.5">
              <div
                className="h-2.5 rounded-r-[4px] bg-institucional-500"
                style={{
                  width: valor === 0 ? 0 : `${Math.max((valor / maximo) * 100, 2)}%`,
                }}
              />
            </div>
            <span className="text-right text-sm tabular-nums text-slate-700">{valor}</span>
          </div>
        ))}

        {filas.length === 0 && (
          <p className="py-2 text-sm text-slate-500">Sin datos todavía.</p>
        )}
      </div>
    </section>
  );
}

const fechaCorta = new Intl.DateTimeFormat("es-AR", { day: "2-digit", month: "2-digit" });
const fechaLarga = new Intl.DateTimeFormat("es-AR", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

// La fecha viene como AAAA-MM-DD; parsearla como local evita el corrimiento de día por UTC.
const aFechaLocal = (iso: string) => new Date(`${iso}T00:00:00`);

interface LineaProps {
  titulo: string;
  subtitulo: string;
  datos: { fecha: string; casos: number }[];
}

function LineaCasosPorDia({ titulo, subtitulo, datos }: LineaProps) {
  const [indiceActivo, setIndiceActivo] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const ANCHO = 560;
  const ALTO = 180;
  const MARGEN = { arriba: 12, abajo: 24, izquierda: 28, derecha: 12 };
  const anchoUtil = ANCHO - MARGEN.izquierda - MARGEN.derecha;
  const altoUtil = ALTO - MARGEN.arriba - MARGEN.abajo;

  const { puntos, maximo } = useMemo(() => {
    const tope = Math.max(...datos.map((d) => d.casos), 1);
    // Techo entero "redondo" para que las líneas de la grilla caigan en enteros.
    const techo = Math.max(Math.ceil(tope / 2) * 2, 2);
    const paso = datos.length > 1 ? anchoUtil / (datos.length - 1) : 0;
    return {
      maximo: techo,
      puntos: datos.map((dia, indice) => ({
        ...dia,
        x: MARGEN.izquierda + indice * paso,
        y: MARGEN.arriba + altoUtil * (1 - dia.casos / techo),
      })),
    };
  }, [datos, anchoUtil, altoUtil, MARGEN.izquierda, MARGEN.arriba]);

  if (datos.length === 0) {
    return null;
  }

  const linea = puntos.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const area = `${linea} L${puntos[puntos.length - 1].x},${MARGEN.arriba + altoUtil} L${puntos[0].x},${MARGEN.arriba + altoUtil} Z`;
  const gridY = [0, maximo / 2, maximo];
  const activo = indiceActivo === null ? null : puntos[indiceActivo];

  function moverCursor(evento: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg) {
      return;
    }
    const caja = svg.getBoundingClientRect();
    const x = ((evento.clientX - caja.left) / caja.width) * ANCHO;
    let cercano = 0;
    for (let i = 1; i < puntos.length; i += 1) {
      if (Math.abs(puntos[i].x - x) < Math.abs(puntos[cercano].x - x)) {
        cercano = i;
      }
    }
    setIndiceActivo(cercano);
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 lg:col-span-2">
      <h3 className="text-sm font-semibold text-slate-800">{titulo}</h3>
      <p className="mt-0.5 text-xs text-slate-500">{subtitulo}</p>

      <div className="relative mt-4">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${ANCHO} ${ALTO}`}
          className="w-full"
          role="img"
          aria-label={`${titulo}: ${datos.reduce((suma, d) => suma + d.casos, 0)} casos en ${datos.length} días`}
          onMouseMove={moverCursor}
          onMouseLeave={() => setIndiceActivo(null)}
        >
          {/* Grilla recesiva con techo y punto medio; la base es el eje. */}
          {gridY.map((valor) => {
            const y = MARGEN.arriba + altoUtil * (1 - valor / maximo);
            return (
              <g key={valor}>
                <line
                  x1={MARGEN.izquierda}
                  x2={ANCHO - MARGEN.derecha}
                  y1={y}
                  y2={y}
                  stroke={valor === 0 ? "#cbd5e1" : "#e2e8f0"}
                  strokeWidth={1}
                />
                <text
                  x={MARGEN.izquierda - 6}
                  y={y + 3.5}
                  textAnchor="end"
                  className="fill-slate-500 text-[10px] tabular-nums"
                >
                  {valor}
                </text>
              </g>
            );
          })}

          {/* Etiquetas de fecha: primera, media y última para no chocar entre sí. */}
          {[0, Math.floor((puntos.length - 1) / 2), puntos.length - 1].map((indice) => (
            <text
              key={indice}
              x={puntos[indice].x}
              y={ALTO - 6}
              textAnchor={indice === 0 ? "start" : indice === puntos.length - 1 ? "end" : "middle"}
              className="fill-slate-500 text-[10px] tabular-nums"
            >
              {fechaCorta.format(aFechaLocal(puntos[indice].fecha))}
            </text>
          ))}

          <path d={area} fill={COLOR_SERIE} opacity={0.08} />
          <path d={linea} fill="none" stroke={COLOR_SERIE} strokeWidth={2} />

          {activo && (
            <g>
              <line
                x1={activo.x}
                x2={activo.x}
                y1={MARGEN.arriba}
                y2={MARGEN.arriba + altoUtil}
                stroke="#94a3b8"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              {/* Marcador ≥8px con anillo de superficie de 2px. */}
              <circle cx={activo.x} cy={activo.y} r={5} fill={COLOR_SERIE} stroke="#ffffff" strokeWidth={2} />
            </g>
          )}
        </svg>

        {activo && (
          <div
            className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 rounded-md bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow"
            style={{
              left: `${(activo.x / ANCHO) * 100}%`,
            }}
          >
            <div className="capitalize">{fechaLarga.format(aFechaLocal(activo.fecha))}</div>
            <div className="font-semibold tabular-nums">{plural(activo.casos, "caso nuevo", "casos nuevos")}</div>
          </div>
        )}
      </div>
    </section>
  );
}

interface ResolucionProps {
  resueltosPorIa: number;
  escalados: number;
}

function BarraResolucion({ resueltosPorIa, escalados }: ResolucionProps) {
  const total = resueltosPorIa + escalados;
  const series = [
    { etiqueta: "Resueltos por la IA", valor: resueltosPorIa, color: COLOR_SERIE },
    { etiqueta: "Con intervención humana", valor: escalados, color: COLOR_OPERADOR },
  ];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="text-sm font-semibold text-slate-800">Resolución de los casos</h3>
      <p className="mt-0.5 text-xs text-slate-500">
        Según la auditoría: un caso escalado contó con un operador aunque después se cierre.
      </p>

      {total === 0 ? (
        <p className="mt-4 py-2 text-sm text-slate-500">Sin datos todavía.</p>
      ) : (
        <>
          {/* Barra apilada 100% con separador de 2px de superficie entre segmentos. */}
          <div className="mt-5 flex h-4 gap-[2px] overflow-hidden rounded-[4px]">
            {series
              .filter((serie) => serie.valor > 0)
              .map((serie) => (
                <div
                  key={serie.etiqueta}
                  title={`${serie.etiqueta}: ${serie.valor}`}
                  style={{
                    width: `${(serie.valor / total) * 100}%`,
                    backgroundColor: serie.color,
                  }}
                />
              ))}
          </div>

          <ul className="mt-4 space-y-2">
            {series.map((serie) => (
              <li key={serie.etiqueta} className="flex items-center gap-2 text-sm">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ backgroundColor: serie.color }}
                />
                <span className="text-slate-600">{serie.etiqueta}</span>
                <span className="ml-auto tabular-nums text-slate-800">
                  {serie.valor}
                  <span className="ml-1 text-xs text-slate-500">
                    ({total === 0 ? "—" : porcentaje.format(serie.valor / total)})
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function Metricas() {
  const { usuario } = useAuth();
  const [datos, setDatos] = useState<DatosMetricas | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    obtenerMetricas()
      .then(setDatos)
      .catch((excepcion: Error) => setError(excepcion.message));
  }, []);

  if (error !== null) {
    return null;
  }

  if (datos === null) {
    return (
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((tarjeta) => (
          <div
            key={tarjeta}
            className="h-[104px] animate-pulse rounded-lg border border-slate-200 bg-white"
          />
        ))}
      </div>
    );
  }

  const automatizacion =
    datos.tasa_automatizacion === null ? "—" : porcentaje.format(datos.tasa_automatizacion);
  const primeraRespuesta =
    datos.minutos_primera_respuesta === null
      ? "—"
      : `${decimal.format(datos.minutos_primera_respuesta)} min`;
  const confianza =
    datos.confianza_promedio === null ? "—" : dosDecimales.format(datos.confianza_promedio);

  return (
    <div className="mb-8">
      <p className="mb-4 text-sm text-slate-600">
        {usuario?.rol === "supervisor"
          ? "Indicadores de todos los casos del organismo."
          : "Indicadores calculados solo sobre los casos asignados a usted."}
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <Tarjeta
          icono={BotMessageSquare}
          etiqueta="Resueltos sin operador"
          valor={automatizacion}
          detalle={`${datos.resueltos_por_ia} de ${datos.total_casos} casos · ${plural(datos.escalados, "escalado", "escalados")}`}
        />
        <Tarjeta
          icono={Repeat2}
          etiqueta="Continuidad entre canales"
          valor={String(datos.casos_con_cambio_canal)}
          detalle={`${plural(datos.casos_con_cambio_canal, "caso siguió", "casos siguieron")} en otro canal`}
        />
        <Tarjeta
          icono={Timer}
          etiqueta="Primera respuesta"
          valor={primeraRespuesta}
          detalle="promedio entre el mensaje y la respuesta del agente"
        />
        <Tarjeta
          icono={Gauge}
          etiqueta="Confianza del clasificador"
          valor={confianza}
          detalle={`umbral de escalado en ${dosDecimales.format(0.6)}`}
        />
        <Tarjeta
          icono={AlarmClock}
          etiqueta="Esperando respuesta"
          valor={String(datos.casos_esperando_respuesta)}
          detalle={`${datos.casos_demorados} hace más de ${datos.horas_umbral_demora} h`}
          alerta={datos.casos_demorados > 0}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <LineaCasosPorDia
          titulo="Casos nuevos por día"
          subtitulo="Casos creados en los últimos 14 días"
          datos={datos.casos_por_dia}
        />
        <BarraResolucion resueltosPorIa={datos.resueltos_por_ia} escalados={datos.escalados} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Barras
          titulo="Casos por estado"
          subtitulo="Recorrido del caso en el organismo"
          datos={datos.por_estado}
          etiquetas={ETIQUETA_ESTADO as Record<EstadoCaso, string>}
          orden={[...ESTADOS]}
        />
        <Barras
          titulo="Casos por canal"
          subtitulo="Canal en el que está la conversación hoy"
          datos={datos.por_canal}
          etiquetas={ETIQUETA_CANAL as Record<Canal, string>}
        />
        <Barras
          titulo="Casos por tipo"
          subtitulo="Naturaleza de la solicitud del ciudadano"
          datos={datos.por_tipo}
          etiquetas={ETIQUETA_TIPO as Record<TipoCaso, string>}
        />
      </div>
    </div>
  );
}
