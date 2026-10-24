import { useState } from "react";
import type { FormEvent } from "react";
import { Download, PencilLine, ShieldAlert } from "lucide-react";

import { darDeBajaTitular, exportarDatosTitular, rectificarTitular } from "../lib/titulares";

interface Props {
  ciudadanoId: string;
  nombre: string;
  /** Se llama después de rectificar o dar de baja, para recargar el caso. */
  onCambio: () => Promise<void> | void;
}

/**
 * Pedidos de acceso, rectificación y supresión de datos (RF-13 y RF-14).
 *
 * El ciudadano los pide por cualquier canal y los resuelve el supervisor desde
 * acá: el agente no da de baja a nadie por un mensaje, porque cualquiera que
 * escriba desde un número podría pedir la baja de los datos de otro.
 */
export function DerechosTitular({ ciudadanoId, nombre, onCambio }: Props) {
  const [abierto, setAbierto] = useState(false);
  const [rectificando, setRectificando] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [campos, setCampos] = useState({ nombre: "", email: "", telefono: "" });

  async function accion(fn: () => Promise<void>) {
    setOcupado(true);
    setMensaje(null);
    try {
      await fn();
    } catch (excepcion) {
      setMensaje(excepcion instanceof Error ? excepcion.message : "No se pudo completar la acción");
    } finally {
      setOcupado(false);
    }
  }

  function descargar() {
    void accion(async () => {
      const datos = await exportarDatosTitular(ciudadanoId);
      const archivo = new Blob([JSON.stringify(datos, null, 2)], { type: "application/json" });
      const enlace = document.createElement("a");
      enlace.href = URL.createObjectURL(archivo);
      enlace.download = `datos-titular-${ciudadanoId.slice(0, 8)}.json`;
      enlace.click();
      URL.revokeObjectURL(enlace.href);
      setMensaje("Se descargó el archivo con todos los datos guardados.");
    });
  }

  function rectificar(evento: FormEvent) {
    evento.preventDefault();
    const cambios = Object.fromEntries(
      Object.entries(campos).filter(([, valor]) => valor.trim() !== ""),
    );
    if (Object.keys(cambios).length === 0) {
      return;
    }
    void accion(async () => {
      await rectificarTitular(ciudadanoId, cambios);
      setCampos({ nombre: "", email: "", telefono: "" });
      setRectificando(false);
      setMensaje("Datos rectificados.");
      await onCambio();
    });
  }

  function darDeBaja() {
    const confirmado = window.confirm(
      `¿Dar de baja los datos de ${nombre}?\n\nSe borran su nombre, DNI, teléfono y correo, y se elimina el contenido de todas sus conversaciones. Los casos y la auditoría se conservan sin datos personales. No se puede deshacer.`,
    );
    if (!confirmado) {
      return;
    }
    void accion(async () => {
      await darDeBajaTitular(ciudadanoId);
      setMensaje("Los datos del titular se dieron de baja.");
      await onCambio();
    });
  }

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <button
        type="button"
        onClick={() => setAbierto(!abierto)}
        className="w-full text-left font-medium text-slate-700"
      >
        Derechos del titular (Ley 25.326) {abierto ? "▾" : "▸"}
      </button>

      {abierto && (
        <div className="mt-2 flex flex-col gap-2">
          <button
            type="button"
            disabled={ocupado}
            onClick={descargar}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:border-institucional-500 disabled:opacity-60"
          >
            <Download size={15} aria-hidden /> Descargar sus datos
          </button>

          <button
            type="button"
            disabled={ocupado}
            onClick={() => setRectificando(!rectificando)}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:border-institucional-500 disabled:opacity-60"
          >
            <PencilLine size={15} aria-hidden /> Rectificar datos
          </button>

          {rectificando && (
            <form onSubmit={rectificar} className="flex flex-col gap-2">
              {(["nombre", "email", "telefono"] as const).map((campo) => (
                <input
                  key={campo}
                  value={campos[campo]}
                  onChange={(evento) => setCampos({ ...campos, [campo]: evento.target.value })}
                  placeholder={
                    { nombre: "Nombre completo", email: "Correo electrónico", telefono: "Teléfono" }[campo]
                  }
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 outline-none focus:border-institucional-500"
                />
              ))}
              <button
                type="submit"
                disabled={ocupado}
                className="rounded-md bg-institucional-600 px-3 py-1.5 font-medium text-white hover:bg-institucional-700 disabled:opacity-50"
              >
                Guardar cambios
              </button>
            </form>
          )}

          <button
            type="button"
            disabled={ocupado}
            onClick={darDeBaja}
            className="inline-flex items-center gap-1.5 rounded-md border border-rose-300 bg-white px-3 py-1.5 font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-60"
          >
            <ShieldAlert size={15} aria-hidden /> Dar de baja y eliminar datos
          </button>

          {mensaje && <p className="text-slate-600">{mensaje}</p>}
        </div>
      )}
    </div>
  );
}
