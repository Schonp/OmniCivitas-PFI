import { useState } from "react";

import { Metricas } from "../componentes/Metricas";
import { PanelPestana, Pestanas, type Pestana } from "../componentes/Pestanas";
import { ListaCasos } from "./ListaCasos";

const PESTANAS: Pestana[] = [
  { id: "casos", etiqueta: "Casos" },
  { id: "estadisticas", etiqueta: "Estadísticas" },
];

export function Panel() {
  const [activa, setActiva] = useState("casos");

  return (
    <div>
      <Pestanas
        pestanas={PESTANAS}
        activa={activa}
        onCambiar={setActiva}
        etiquetaAria="Secciones del panel"
      />

      <PanelPestana id="casos" activa={activa}>
        <ListaCasos />
      </PanelPestana>

      <PanelPestana id="estadisticas" activa={activa}>
        <Metricas />
      </PanelPestana>
    </div>
  );
}
