export type EstadoCaso = "abierto" | "en_progreso" | "escalado" | "cerrado";
export type TipoCaso = "consulta" | "reclamo" | "reserva" | "tramite";
export type Canal = "whatsapp" | "email" | "voz";
export type ActorInteraccion = "ciudadano" | "agente_ia" | "operador";
export type RolUsuario = "operador" | "supervisor";

export type MotivoCierre =
  | "resuelto"
  | "derivado"
  | "sin_respuesta_del_ciudadano"
  | "duplicado"
  | "fuera_de_alcance";

export const MOTIVOS_CIERRE: MotivoCierre[] = [
  "resuelto",
  "derivado",
  "sin_respuesta_del_ciudadano",
  "duplicado",
  "fuera_de_alcance",
];

export const ETIQUETA_MOTIVO: Record<MotivoCierre, string> = {
  resuelto: "Resuelto",
  derivado: "Derivado a otra área",
  sin_respuesta_del_ciudadano: "Sin respuesta del ciudadano",
  duplicado: "Duplicado",
  fuera_de_alcance: "Fuera de alcance",
};

export interface Usuario {
  id: string;
  email: string;
  nombre: string;
  rol: RolUsuario;
  activo: boolean;
  created_at: string;
}

export interface CiudadanoResumen {
  id: string;
  nombre: string;
  documento: string;
}

export interface OperadorResumen {
  id: string;
  nombre: string;
}

export interface Caso {
  id: string;
  referencia: string;
  ciudadano_id: string;
  ciudadano: CiudadanoResumen;
  operador_asignado: OperadorResumen | null;
  tipo: TipoCaso;
  estado: EstadoCaso;
  canal_origen: Canal;
  canal_actual: Canal;
  operador_asignado_id: string | null;
  motivo_cierre: MotivoCierre | null;
  titulo: string | null;
  resumen_ia: string | null;
  resumen_ia_generado_en: string | null;
  esperando_desde: string | null;
  created_at: string;
  updated_at: string;
}

export type EstadoReserva = "confirmada" | "cancelada" | "atendida" | "ausente";

export const ETIQUETA_ESTADO_RESERVA: Record<EstadoReserva, string> = {
  confirmada: "Confirmado",
  cancelada: "Cancelado",
  atendida: "Atendido",
  ausente: "Ausente",
};

export interface Reserva {
  id: string;
  caso_id: string;
  referencia: string;
  ciudadano: CiudadanoResumen;
  fecha_hora: string;
  estado: EstadoReserva;
  motivo_cancelacion: string | null;
  cancelada_en: string | null;
  recordatorio_enviado_en: string | null;
  created_at: string;
}

export interface DiaBloqueado {
  id: string;
  turno_id: string | null;
  fecha: string;
  motivo: string;
}

export interface Turno {
  id: string;
  nombre: string;
  descripcion: string;
  sede: string | null;
  dias_atencion: number[];
  hora_apertura: string;
  hora_cierre: string;
  duracion_minutos: number;
  cupos_por_horario: number;
  anticipacion_maxima_dias: number;
  horario: string;
  capacidad: number;
  ocupados: number;
  reservas: Reserva[];
  bloqueos: DiaBloqueado[];
}

export interface DocumentoConocimiento {
  id: string;
  titulo: string;
  contenido: string;
  nombre_archivo: string | null;
  general: boolean;
  created_at: string;
}

export interface GrupoReclamo {
  id: string;
  tema: string;
  casos: Caso[];
  generado_en: string;
}

export interface Interaccion {
  id: string;
  caso_id: string;
  contenido: string;
  canal: Canal;
  actor: ActorInteraccion;
  interna: boolean;
  timestamp: string;
}

/** Un caso que llegó a la bandeja de quien mira: derivado por el agente o asignado. */
export interface AvisoCaso {
  caso: Caso;
  motivo: "derivado" | "asignado";
  momento: string;
}

export interface UltimoMensaje {
  actor: ActorInteraccion;
  canal: Canal;
  contenido: string;
  timestamp: string;
}

export interface CasoEnFicha {
  id: string;
  referencia: string;
  tipo: TipoCaso;
  estado: EstadoCaso;
  canal_origen: Canal;
  canal_actual: Canal;
  operador_asignado: OperadorResumen | null;
  created_at: string;
  updated_at: string;
  mensajes: number;
  /** Los canales por los que pasó la conversación, en orden. */
  recorrido: Canal[];
  /** Si no, la ficha no trae el resumen ni el último mensaje del caso. */
  puede_abrir: boolean;
  resumen_ia: string | null;
  ultimo_mensaje: UltimoMensaje | null;
}

export interface FichaCiudadano {
  id: string;
  nombre: string;
  documento: string;
  identificado: boolean;
  canales: Canal[];
  primer_contacto: string | null;
  ultimo_contacto: string | null;
  casos: CasoEnFicha[];
}

export interface Auditoria {
  id: string;
  caso_id: string;
  accion: string;
  actor: string;
  actor_tipo: ActorInteraccion;
  timestamp: string;
  metadata: Record<string, unknown> | null;
}

export const ESTADOS: EstadoCaso[] = ["abierto", "en_progreso", "escalado", "cerrado"];

// Los chips de la bandeja activa: un caso cerrado se archiva y ya no se filtra
// por ahí, tiene su propia solapa.
export const ESTADOS_ACTIVOS: EstadoCaso[] = ESTADOS.filter((estado) => estado !== "cerrado");

export const ETIQUETA_ESTADO: Record<EstadoCaso, string> = {
  abierto: "Abierto",
  en_progreso: "En progreso",
  escalado: "Escalado",
  cerrado: "Cerrado",
};

export const ETIQUETA_TIPO: Record<TipoCaso, string> = {
  consulta: "Consulta",
  reclamo: "Reclamo",
  reserva: "Reserva",
  tramite: "Trámite",
};

export const ETIQUETA_CANAL: Record<Canal, string> = {
  whatsapp: "WhatsApp",
  email: "Email",
  voz: "Llamada",
};

export const ETIQUETA_ACTOR: Record<ActorInteraccion, string> = {
  ciudadano: "Ciudadano",
  agente_ia: "Agente IA",
  operador: "Operador",
};
