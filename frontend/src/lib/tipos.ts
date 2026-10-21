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
  ciudadano_id: string;
  ciudadano: CiudadanoResumen;
  operador_asignado: OperadorResumen | null;
  tipo: TipoCaso;
  estado: EstadoCaso;
  canal_origen: Canal;
  canal_actual: Canal;
  operador_asignado_id: string | null;
  motivo_cierre: MotivoCierre | null;
  resumen_ia: string | null;
  resumen_ia_generado_en: string | null;
  esperando_desde: string | null;
  created_at: string;
  updated_at: string;
}

export interface Reserva {
  id: string;
  caso_id: string;
  ciudadano: CiudadanoResumen;
  fecha_hora: string;
  created_at: string;
}

export interface Turno {
  id: string;
  nombre: string;
  descripcion: string;
  reservas: Reserva[];
}

export interface DocumentoConocimiento {
  id: string;
  titulo: string;
  contenido: string;
  nombre_archivo: string | null;
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
