import { descargar, request, requestConTotal } from "./api";
import type {
  Auditoria,
  Caso,
  EstadoCaso,
  Interaccion,
  MotivoCierre,
  Usuario,
} from "./tipos";

interface RespuestaToken {
  access_token: string;
  refresh_token: string;
}

export async function login(email: string, password: string): Promise<RespuestaToken> {
  return request<RespuestaToken>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function obtenerPerfil(): Promise<Usuario> {
  return request<Usuario>("/api/auth/perfil");
}

export interface FiltrosCasos {
  estado?: EstadoCaso;
  q?: string;
  sinAsignar?: boolean;
  limite?: number;
  desplazamiento?: number;
}

export async function listarCasos(
  filtros: FiltrosCasos = {},
): Promise<{ datos: Caso[]; total: number }> {
  const query = new URLSearchParams();
  if (filtros.estado) query.set("estado", filtros.estado);
  if (filtros.q) query.set("q", filtros.q);
  if (filtros.sinAsignar) query.set("sin_asignar", "true");
  query.set("limite", String(filtros.limite ?? 20));
  query.set("desplazamiento", String(filtros.desplazamiento ?? 0));

  return requestConTotal<Caso[]>(`/api/casos?${query.toString()}`);
}

export interface ConteoCasos {
  todos: number;
  por_estado: Partial<Record<EstadoCaso, number>>;
}

export async function contarCasos(): Promise<ConteoCasos> {
  return request<ConteoCasos>("/api/casos/conteos");
}

export async function listarUsuarios(): Promise<Usuario[]> {
  return request<Usuario[]>("/api/usuarios");
}

export async function exportarCasos(): Promise<void> {
  return descargar("/api/casos/exportar", "casos-omnicivitas.csv");
}

export async function obtenerCaso(casoId: string): Promise<Caso> {
  return request<Caso>(`/api/casos/${casoId}`);
}

export async function listarInteracciones(casoId: string): Promise<Interaccion[]> {
  return request<Interaccion[]>(`/api/casos/${casoId}/interacciones`);
}

export async function listarAuditoria(casoId: string): Promise<Auditoria[]> {
  return request<Auditoria[]>(`/api/casos/${casoId}/auditoria`);
}

export async function cambiarEstadoCaso(
  casoId: string,
  estado: EstadoCaso,
  motivo?: MotivoCierre,
): Promise<Caso> {
  return request<Caso>(`/api/casos/${casoId}/estado`, {
    method: "PATCH",
    body: JSON.stringify({ estado, motivo: motivo ?? null }),
  });
}

export async function asignarCaso(casoId: string, operadorId: string | null): Promise<Caso> {
  return request<Caso>(`/api/casos/${casoId}/asignacion`, {
    method: "PATCH",
    body: JSON.stringify({ operador_asignado_id: operadorId }),
  });
}

export async function generarResumenCaso(casoId: string): Promise<Caso> {
  return request<Caso>(`/api/casos/${casoId}/resumen`, { method: "POST" });
}

export async function responderCaso(
  casoId: string,
  contenido: string,
  interna = false,
): Promise<Interaccion> {
  return request<Interaccion>(`/api/casos/${casoId}/respuesta`, {
    method: "POST",
    body: JSON.stringify({ contenido, interna }),
  });
}
