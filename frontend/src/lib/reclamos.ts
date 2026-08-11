import { request } from "./api";
import type { GrupoReclamo } from "./tipos";

export async function listarGruposReclamos(): Promise<GrupoReclamo[]> {
  return request<GrupoReclamo[]>("/api/reclamos/grupos");
}

export async function generarGruposReclamos(): Promise<GrupoReclamo[]> {
  return request<GrupoReclamo[]>("/api/reclamos/grupos/generar", { method: "POST" });
}
