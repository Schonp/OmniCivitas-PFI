import { request } from "./api";
import type { Turno } from "./tipos";

export async function listarTurnos(): Promise<Turno[]> {
  return request<Turno[]>("/api/turnos");
}
