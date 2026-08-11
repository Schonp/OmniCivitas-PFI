import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { tokenStore } from "./lib/api";
import { login as loginRequest, obtenerPerfil } from "./lib/casos";
import type { Usuario } from "./lib/tipos";

interface EstadoAuth {
  usuario: Usuario | null;
  cargando: boolean;
  iniciarSesion: (email: string, password: string) => Promise<void>;
  cerrarSesion: () => void;
}

const AuthContext = createContext<EstadoAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    // Un token guardado puede estar vencido: se valida contra el backend
    // antes de dar por iniciada la sesión.
    if (!tokenStore.get()) {
      setCargando(false);
      return;
    }
    obtenerPerfil()
      .then(setUsuario)
      .catch(() => tokenStore.clear())
      .finally(() => setCargando(false));
  }, []);

  const iniciarSesion = useCallback(async (email: string, password: string) => {
    const token = await loginRequest(email, password);
    tokenStore.set(token.access_token);
    setUsuario(await obtenerPerfil());
  }, []);

  const cerrarSesion = useCallback(() => {
    tokenStore.clear();
    setUsuario(null);
  }, []);

  return (
    <AuthContext.Provider value={{ usuario, cargando, iniciarSesion, cerrarSesion }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): EstadoAuth {
  const contexto = useContext(AuthContext);
  if (contexto === null) {
    throw new Error("useAuth debe usarse dentro de AuthProvider");
  }
  return contexto;
}
