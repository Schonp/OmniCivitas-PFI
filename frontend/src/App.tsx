import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth";
import { Layout } from "./componentes/Layout";
import { Conocimiento } from "./paginas/Conocimiento";
import { DetalleCaso } from "./paginas/DetalleCaso";
import { Login } from "./paginas/Login";
import { Panel } from "./paginas/Panel";
import { ReclamosComunes } from "./paginas/ReclamosComunes";
import { Turnos } from "./paginas/Turnos";

function RutaProtegida({ children }: { children: React.ReactNode }) {
  const { usuario, cargando } = useAuth();

  if (cargando) {
    return <p className="p-8 text-slate-500">Cargando…</p>;
  }
  if (!usuario) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RutaProtegida>
            <Layout />
          </RutaProtegida>
        }
      >
        <Route path="/casos" element={<Panel />} />
        <Route path="/casos/:casoId" element={<DetalleCaso />} />
        <Route path="/turnos" element={<Turnos />} />
        <Route path="/conocimiento" element={<Conocimiento />} />
        <Route path="/reclamos-comunes" element={<ReclamosComunes />} />
      </Route>
      <Route path="*" element={<Navigate to="/casos" replace />} />
    </Routes>
  );
}
