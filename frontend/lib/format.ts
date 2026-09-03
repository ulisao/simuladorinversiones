export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 2,
  });
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toLocaleString("es-AR", { maximumFractionDigits: 2 })}%`;
}

export function formatNumero(
  value: number | null | undefined,
  decimales = 2,
): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("es-AR", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

/**
 * El backend manda fechas ISO sin zona horaria (ej. "2026-08-29T22:30:00").
 * Si no se puede parsear se devuelve el string original, sin romper la vista.
 */
export function formatFechaHora(value: string | null | undefined): string {
  if (!value) return "—";
  const fecha = new Date(value);
  if (Number.isNaN(fecha.getTime())) return value;
  return fecha.toLocaleString("es-AR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
