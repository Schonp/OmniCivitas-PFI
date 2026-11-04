import { Link, NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth";
import { AvisoDerivados } from "./AvisoDerivados";
import logoOmniCivitas from "../assets/logo-omnicivitas.png";

const ESTILO_NAV_BASE = "rounded-md px-3 py-1.5 text-sm font-medium transition";

function EnlaceNav({ a, children }: { a: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={a}
      className={({ isActive }) =>
        `${ESTILO_NAV_BASE} ${
          isActive
            ? "bg-institucional-600 text-white"
            : "text-institucional-100 hover:bg-institucional-600/60 hover:text-white"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export function Layout() {
  const { usuario, cerrarSesion } = useAuth();
  const esSupervisor = usuario?.rol === "supervisor";

  return (
    <div className="min-h-full">
      <header className="bg-institucional-700 text-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <Link to="/casos" className="flex items-center gap-3">
            <img
              src={logoOmniCivitas}
              alt="OmniCivitas"
              width={512}
              height={136}
              className="h-9 w-auto"
            />
            <span className="hidden border-l border-institucional-500 pl-3 text-sm text-institucional-100 sm:inline">
              Panel de atención ciudadana
            </span>
          </Link>

          {usuario && (
            <div className="flex items-center gap-4 text-sm">
              <AvisoDerivados />
              <div className="text-right leading-tight">
                <div className="font-medium">{usuario.nombre}</div>
                <div className="text-institucional-100 capitalize">{usuario.rol}</div>
              </div>
              <button
                type="button"
                onClick={cerrarSesion}
                className="rounded-md border border-institucional-500 px-3 py-1.5 transition hover:bg-institucional-600"
              >
                Cerrar sesión
              </button>
            </div>
          )}
        </div>

        <nav
          aria-label="Secciones del panel"
          className="mx-auto flex max-w-7xl flex-wrap items-center gap-1 px-6 pb-3"
        >
          <EnlaceNav a="/casos">Casos</EnlaceNav>
          <EnlaceNav a="/turnos">Turnos</EnlaceNav>
          <EnlaceNav a="/conocimiento">Base de conocimiento</EnlaceNav>
          {esSupervisor && <EnlaceNav a="/reclamos-comunes">Reclamos en común</EnlaceNav>}
          <EnlaceNav a="/telefono">Teléfono de prueba</EnlaceNav>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
