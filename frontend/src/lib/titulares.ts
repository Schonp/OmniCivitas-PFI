import { request } from "./api";
import type { CiudadanoResumen } from "./tipos";

/** Derechos del titular de los datos (Ley 25.326). Solo el supervisor. */

export interface Rectificacion {
  nombre?: string;
  email?: string;
  telefono?: string;
}

export async function exportarDatosTitular(ciudadanoId: string): Promise<unknown> {
  return request<unknown>(`/api/ciudadanos/${ciudadanoId}/datos`);
}

export async function rectificarTitular(
  ciudadanoId: string,
  datos: Rectificacion,
): Promise<CiudadanoResumen> {
  return request<CiudadanoResumen>(`/api/ciudadanos/${ciudadanoId}`, {
    method: "PATCH",
    body: JSON.stringify(datos),
  });
}

export async function darDeBajaTitular(ciudadanoId: string): Promise<void> {
  return request<void>(`/api/ciudadanos/${ciudadanoId}/baja`, { method: "POST" });
}
