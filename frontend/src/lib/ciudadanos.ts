import { request } from "./api";
import type { FichaCiudadano } from "./tipos";

export async function obtenerFicha(ciudadanoId: string): Promise<FichaCiudadano> {
  return request<FichaCiudadano>(`/api/ciudadanos/${ciudadanoId}/ficha`);
}
