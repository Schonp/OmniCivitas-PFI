const fechaHora = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const hora = new Intl.DateTimeFormat("es-AR", { hour: "2-digit", minute: "2-digit" });

export const formatearFechaHora = (iso: string) => fechaHora.format(new Date(iso));
export const formatearHora = (iso: string) => hora.format(new Date(iso));

export const idCorto = (id: string) => id.slice(0, 8).toUpperCase();
