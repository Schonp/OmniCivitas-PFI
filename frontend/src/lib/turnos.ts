import { ApiError, request } from "./api";
import type { DiaBloqueado, Reserva, Turno } from "./tipos";

export async function listarTurnos(desde: string, dias = 7): Promise<Turno[]> {
  return request<Turno[]>(`/api/turnos?desde=${desde}&dias=${dias}`);
}

export async function cancelarReserva(reservaId: string, motivo?: string): Promise<Reserva> {
  return request<Reserva>(`/api/turnos/reservas/${reservaId}/cancelar`, {
    method: "POST",
    body: JSON.stringify({ motivo: motivo || null }),
  });
}

export async function registrarAsistencia(
  reservaId: string,
  estado: "atendida" | "ausente",
): Promise<Reserva> {
  return request<Reserva>(`/api/turnos/reservas/${reservaId}/asistencia`, {
    method: "POST",
    body: JSON.stringify({ estado }),
  });
}

export type CanalDeReserva = "whatsapp" | "email" | "voz";

/** La fecha y hora van sin zona: son las del organismo ("2026-10-29T09:30"). */
export async function reservarDesdePanel(
  turnoId: string,
  datos: { documento: string; nombre?: string; fecha_hora: string; canal: CanalDeReserva },
): Promise<Reserva> {
  return request<Reserva>(`/api/turnos/${turnoId}/reservas`, {
    method: "POST",
    body: JSON.stringify({ ...datos, nombre: datos.nombre || null }),
  });
}

export async function reprogramarReserva(reservaId: string, fechaHora: string): Promise<Reserva> {
  return request<Reserva>(`/api/turnos/reservas/${reservaId}/reprogramar`, {
    method: "POST",
    body: JSON.stringify({ fecha_hora: fechaHora }),
  });
}

export interface CambiosAgenda {
  sede?: string | null;
  dias_atencion?: number[];
  hora_apertura?: string;
  hora_cierre?: string;
  duracion_minutos?: number;
  cupos_por_horario?: number;
  anticipacion_maxima_dias?: number;
}

export async function configurarAgenda(turnoId: string, cambios: CambiosAgenda): Promise<Turno> {
  return request<Turno>(`/api/turnos/${turnoId}`, { method: "PATCH", body: JSON.stringify(cambios) });
}

export async function listarBloqueos(): Promise<DiaBloqueado[]> {
  return request<DiaBloqueado[]>("/api/turnos/bloqueos/proximos");
}

export async function bloquearDia(datos: {
  fecha: string;
  motivo: string;
  turno_id: string | null;
}): Promise<{ bloqueo: DiaBloqueado; afectados: Reserva[] }> {
  return request(`/api/turnos/bloqueos`, { method: "POST", body: JSON.stringify(datos) });
}

export async function desbloquearDia(bloqueoId: string): Promise<void> {
  return request<void>(`/api/turnos/bloqueos/${bloqueoId}`, { method: "DELETE" });
}

export interface ResumenRecordatorios {
  dia: string;
  total: number;
  enviados: number;
  no_enviados: { referencia: string; motivo: string | null }[];
}

export async function enviarRecordatorios(): Promise<ResumenRecordatorios> {
  return request<ResumenRecordatorios>("/api/turnos/recordatorios", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

/** Los horarios libres que la API propone cuando el pedido no se puede hacer. */
export function alternativasDe(error: unknown): string[] {
  if (error instanceof ApiError && error.detalle && typeof error.detalle === "object") {
    const alternativas = (error.detalle as { alternativas?: unknown }).alternativas;
    if (Array.isArray(alternativas)) return alternativas.map(String);
  }
  return [];
}
