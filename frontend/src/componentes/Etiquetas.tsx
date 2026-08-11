import { Globe, Mail, MessageCircle, Phone, type LucideIcon } from "lucide-react";

import {
  ETIQUETA_CANAL,
  ETIQUETA_ESTADO,
  ETIQUETA_TIPO,
  type Canal,
  type EstadoCaso,
  type TipoCaso,
} from "../lib/tipos";

const COLOR_ESTADO: Record<EstadoCaso, string> = {
  abierto: "bg-blue-100 text-blue-900 ring-blue-300",
  en_progreso: "bg-amber-100 text-amber-900 ring-amber-300",
  escalado: "bg-rose-100 text-rose-900 ring-rose-300",
  cerrado: "bg-slate-200 text-slate-700 ring-slate-400",
};

const ICONO_CANAL: Record<Canal, LucideIcon> = {
  whatsapp: MessageCircle,
  email: Mail,
  voz: Phone,
  web: Globe,
};

export function EstadoBadge({ estado }: { estado: EstadoCaso }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${COLOR_ESTADO[estado]}`}
    >
      {ETIQUETA_ESTADO[estado]}
    </span>
  );
}

export function TipoBadge({ tipo }: { tipo: TipoCaso }) {
  return (
    <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
      {ETIQUETA_TIPO[tipo]}
    </span>
  );
}

export function CanalBadge({ canal }: { canal: Canal }) {
  const Icono = ICONO_CANAL[canal];
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-institucional-50 px-2 py-0.5 text-xs font-medium text-institucional-700">
      <Icono size={12} strokeWidth={2} aria-hidden />
      {ETIQUETA_CANAL[canal]}
    </span>
  );
}

export function RecorridoCanal({ origen, actual }: { origen: Canal; actual: Canal }) {
  if (origen === actual) {
    return <CanalBadge canal={origen} />;
  }
  return (
    <span className="inline-flex items-center gap-1">
      <CanalBadge canal={origen} />
      <span className="text-slate-400" aria-label="derivado a">
        →
      </span>
      <CanalBadge canal={actual} />
    </span>
  );
}
