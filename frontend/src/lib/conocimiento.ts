import { request } from "./api";
import type { DocumentoConocimiento } from "./tipos";

export async function listarDocumentos(): Promise<DocumentoConocimiento[]> {
  return request<DocumentoConocimiento[]>("/api/conocimiento");
}

export async function crearDocumento(datos: {
  titulo: string;
  contenido: string;
  nombre_archivo?: string;
  general?: boolean;
}): Promise<DocumentoConocimiento> {
  return request<DocumentoConocimiento>("/api/conocimiento", {
    method: "POST",
    body: JSON.stringify(datos),
  });
}

export async function borrarDocumento(documentoId: string): Promise<void> {
  return request<void>(`/api/conocimiento/${documentoId}`, { method: "DELETE" });
}
