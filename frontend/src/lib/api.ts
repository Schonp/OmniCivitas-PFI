const BASE_URL = import.meta.env.VITE_API_URL ?? "";
const TOKEN_KEY = "omnicivitas.access_token";

export class ApiError extends Error {
  status: number;
  /** El `detail` tal como lo manda la API: a veces trae más que un texto. */
  detalle: unknown;

  constructor(status: number, message: string, detalle?: unknown) {
    super(message);
    this.status = status;
    this.detalle = detalle;
  }
}

/** Un mensaje legible a partir del `detail` de FastAPI, sea texto, un objeto
 * con `motivo` o la lista de errores de validación. */
function mensajeDeError(status: number, detalle: unknown): string {
  if (typeof detalle === "string") return detalle;
  if (detalle && typeof detalle === "object" && "motivo" in detalle) {
    return String((detalle as { motivo: unknown }).motivo);
  }
  if (Array.isArray(detalle)) {
    return detalle.map((error) => (error as { msg?: string }).msg ?? "").filter(Boolean).join("; ");
  }
  return `Error ${status}`;
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      tokenStore.clear();
    }
    const cuerpo = await response.json().catch(() => null);
    throw new ApiError(response.status, mensajeDeError(response.status, cuerpo?.detail), cuerpo?.detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Igual que `request`, pero devuelve además el total de la paginación. */
export async function requestConTotal<T>(
  path: string,
  options: RequestInit = {},
): Promise<{ datos: T; total: number }> {
  const token = tokenStore.get();

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      tokenStore.clear();
    }
    const cuerpo = await response.json().catch(() => null);
    throw new ApiError(response.status, mensajeDeError(response.status, cuerpo?.detail), cuerpo?.detail);
  }

  const datos = (await response.json()) as T;
  const total = Number(response.headers.get("X-Total-Count") ?? 0);
  return { datos, total };
}

export async function descargar(path: string, nombreArchivo: string): Promise<void> {
  const token = tokenStore.get();
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new ApiError(response.status, `No se pudo exportar (${response.status})`);
  }

  const url = URL.createObjectURL(await response.blob());
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombreArchivo;
  enlace.click();
  URL.revokeObjectURL(url);
}
