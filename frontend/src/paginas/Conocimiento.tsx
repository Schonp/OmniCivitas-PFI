import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { AlertCircle, BookOpen, FileText, Sparkles, Trash2, Upload } from "lucide-react";

import { useAuth } from "../auth";
import { borrarDocumento, crearDocumento, listarDocumentos } from "../lib/conocimiento";
import { formatearFechaHora } from "../lib/formato";
import type { DocumentoConocimiento } from "../lib/tipos";

const MAX_CONTENIDO = 50_000;

export function Conocimiento() {
  const { usuario } = useAuth();
  const esSupervisor = usuario?.rol === "supervisor";

  const [documentos, setDocumentos] = useState<DocumentoConocimiento[]>([]);
  const [titulo, setTitulo] = useState("");
  const [contenido, setContenido] = useState("");
  const [nombreArchivo, setNombreArchivo] = useState<string | null>(null);
  const [general, setGeneral] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inputArchivo = useRef<HTMLInputElement>(null);

  async function cargar() {
    try {
      setDocumentos(await listarDocumentos());
      setError(null);
    } catch (excepcion) {
      setError(
        excepcion instanceof Error ? excepcion.message : "No se pudo cargar el conocimiento",
      );
    } finally {
      setCargando(false);
    }
  }

  useEffect(() => {
    void cargar();
  }, []);

  function leerArchivo(archivo: File) {
    // El archivo se lee en el navegador y viaja como texto plano: mismo
    // tratamiento que el contenido pegado a mano.
    const lector = new FileReader();
    lector.onload = () => {
      setContenido(String(lector.result ?? "").slice(0, MAX_CONTENIDO));
      setNombreArchivo(archivo.name);
      if (titulo.trim() === "") {
        setTitulo(archivo.name.replace(/\.(txt|md)$/i, ""));
      }
    };
    lector.readAsText(archivo);
  }

  async function guardar(evento: FormEvent) {
    evento.preventDefault();
    if (titulo.trim() === "" || contenido.trim() === "") {
      return;
    }
    setGuardando(true);
    try {
      await crearDocumento({
        titulo: titulo.trim(),
        contenido: contenido.trim(),
        nombre_archivo: nombreArchivo ?? undefined,
        general,
      });
      setTitulo("");
      setContenido("");
      setNombreArchivo(null);
      setGeneral(false);
      if (inputArchivo.current) {
        inputArchivo.current.value = "";
      }
      await cargar();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  }

  async function borrar(documentoId: string) {
    try {
      await borrarDocumento(documentoId);
      await cargar();
    } catch (excepcion) {
      setError(excepcion instanceof Error ? excepcion.message : "No se pudo borrar");
    }
  }

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-xl font-semibold text-slate-900">Base de conocimiento</h2>
        <p className="text-sm text-slate-600">
          Información del organismo (trámites, requisitos, horarios) que la IA usa como
          contexto para responder consultas de los ciudadanos, y pautas generales que
          definen cómo atiende en todas las conversaciones.
        </p>
      </div>

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
          <AlertCircle size={16} aria-hidden />
          {error}
        </p>
      )}

      {esSupervisor && (
        <form
          onSubmit={guardar}
          className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <BookOpen size={16} className="text-institucional-600" aria-hidden />
            Cargar información
          </h3>

          <div className="mt-3 grid gap-3">
            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Título</span>
              <input
                type="text"
                value={titulo}
                maxLength={200}
                onChange={(evento) => setTitulo(evento.target.value)}
                placeholder="Ej.: Requisitos para renovar la licencia de conducir"
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block font-medium text-slate-700">Contenido</span>
              <textarea
                rows={6}
                value={contenido}
                maxLength={MAX_CONTENIDO}
                onChange={(evento) => setContenido(evento.target.value)}
                placeholder="Pegue el texto acá, o cargue un archivo .txt / .md con el botón de abajo."
                className="w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-institucional-500 focus:ring-2 focus:ring-institucional-100"
              />
            </label>

            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={general}
                onChange={(evento) => setGeneral(evento.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-institucional-600 focus:ring-institucional-500"
              />
              <span>
                <span className="font-medium">Pauta general.</span> La IA la aplica en todas
                las conversaciones, no solo cuando el mensaje del ciudadano menciona el tema.
              </span>
            </label>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-institucional-500 hover:text-institucional-700">
                <Upload size={15} aria-hidden />
                {nombreArchivo ?? "Cargar desde archivo (.txt, .md)"}
                <input
                  ref={inputArchivo}
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  className="sr-only"
                  onChange={(evento) => {
                    const archivo = evento.target.files?.[0];
                    if (archivo) {
                      leerArchivo(archivo);
                    }
                  }}
                />
              </label>

              <button
                type="submit"
                disabled={guardando || titulo.trim() === "" || contenido.trim() === ""}
                className="rounded-md bg-institucional-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-institucional-700 active:translate-y-px disabled:opacity-50"
              >
                {guardando ? "Guardando…" : "Guardar en la base"}
              </button>
            </div>
          </div>
        </form>
      )}

      {!esSupervisor && (
        <p className="mb-6 rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-600">
          La carga y el borrado de documentos los gestiona un supervisor.
        </p>
      )}

      {cargando && <p className="text-slate-500">Cargando documentos…</p>}

      {!cargando && documentos.length === 0 && !error && (
        <p className="rounded-lg border border-slate-300 bg-white px-4 py-10 text-center text-slate-600">
          La base de conocimiento está vacía. La IA responde solo con lo que sabe del caso.
        </p>
      )}

      <div className="space-y-3">
        {documentos.map((documento) => (
          <article
            key={documento.id}
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold text-slate-900">{documento.titulo}</h3>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  {documento.general && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-institucional-50 px-1.5 py-0.5 font-medium text-institucional-700">
                      <Sparkles size={11} aria-hidden />
                      Pauta general
                    </span>
                  )}
                  {documento.nombre_archivo && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
                      <FileText size={11} aria-hidden />
                      {documento.nombre_archivo}
                    </span>
                  )}
                  <span>Cargado el {formatearFechaHora(documento.created_at)}</span>
                </p>
              </div>

              {esSupervisor && (
                <button
                  type="button"
                  onClick={() => void borrar(documento.id)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:border-rose-400 hover:text-rose-700"
                >
                  <Trash2 size={13} aria-hidden />
                  Borrar
                </button>
              )}
            </div>

            <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-slate-700">
              {documento.contenido.length > 600
                ? `${documento.contenido.slice(0, 600)}…`
                : documento.contenido}
            </p>
          </article>
        ))}
      </div>
    </div>
  );
}
