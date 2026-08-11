import { request } from "./api";

export interface Metricas {
  total_casos: number;
  por_estado: Record<string, number>;
  por_canal: Record<string, number>;
  por_tipo: Record<string, number>;
  escalados: number;
  resueltos_por_ia: number;
  tasa_automatizacion: number | null;
  casos_con_cambio_canal: number;
  casos_esperando_respuesta: number;
  casos_demorados: number;
  horas_umbral_demora: number;
  minutos_primera_respuesta: number | null;
  confianza_promedio: number | null;
  casos_por_dia: { fecha: string; casos: number }[];
}

export async function obtenerMetricas(): Promise<Metricas> {
  return request<Metricas>("/api/metricas");
}
