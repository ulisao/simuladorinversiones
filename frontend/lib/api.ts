import type {
  Trade,
  TradeCreateInput,
  TradeCloseInput,
  Dashboard,
  BrokerConfig,
  PrecioMercado,
  Senales,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8123";

/**
 * FastAPI devuelve los errores como {"detail": "mensaje en español"}.
 * Si el cuerpo tiene esa forma se usa el mensaje tal cual, para que la UI
 * muestre algo legible en vez del cuerpo crudo de la respuesta.
 */
async function mensajeDeError(res: Response, path: string): Promise<string> {
  const body = await res.text();
  try {
    const parsed: unknown = JSON.parse(body);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as { detail?: unknown }).detail === "string"
    ) {
      return (parsed as { detail: string }).detail;
    }
  } catch {
    // El backend no devolvió JSON: se cae al mensaje genérico de abajo.
  }
  return `Error ${res.status} en ${path}: ${body}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(await mensajeDeError(res, path));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  getDashboard: () => request<Dashboard>("/dashboard"),
  getTrades: () => request<Trade[]>("/trades"),
  createTrade: (data: TradeCreateInput) =>
    request<Trade>("/trades", { method: "POST", body: JSON.stringify(data) }),
  closeTrade: (id: number, data: TradeCloseInput) =>
    request<Trade>(`/trades/${id}/cerrar`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteTrade: (id: number) =>
    request<void>(`/trades/${id}`, { method: "DELETE" }),
  getBrokerConfig: () => request<BrokerConfig>("/broker-config"),
  updateBrokerConfig: (data: {
    comision_broker: number;
    derechos_mercado: number;
    iva: number;
  }) =>
    request<BrokerConfig>("/broker-config", {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  getPrecioMercado: (ticker: string) =>
    request<PrecioMercado>(`/market/precio/${encodeURIComponent(ticker)}`),
  getSenales: () => request<Senales>("/senales"),
};
