import type {
  Trade,
  TradeCreateInput,
  TradeCloseInput,
  Dashboard,
  BrokerConfig,
  PrecioMercado,
  Senales,
  SenalesSmartMoney,
  SenalesBonos,
  SaldoIOL,
  Ccl,
  SyncSheets,
  EstadoSheets,
} from "./types";

/**
 * Todo pasa por el proxy de Next (`app/api/backend/[...path]/route.ts`), nunca
 * directo contra la API.
 *
 * El motivo es la `X-API-Key`: antes viajaba como `NEXT_PUBLIC_API_KEY` y Next
 * incrusta esas variables en el bundle del navegador, así que publicar el
 * frontend era publicar la clave. Ahora la clave vive en `BACKEND_API_KEY`, del
 * lado del servidor, y el browser solo habla con su propio origen.
 *
 * A dónde apunta el proxy se configura con `BACKEND_URL` (ver
 * `.env.local.example`).
 */
const API_URL = "/api/backend";

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
  if (res.status === 401) {
    return "El backend rechazó la clave. Revisá BACKEND_API_KEY del frontend (tiene que coincidir con API_KEY del backend).";
  }
  if (res.status === 503 && body.includes("API_KEY")) {
    return "El backend no tiene API_KEY configurada. Cargala en backend/.env (ver .env.example).";
  }
  return `Error ${res.status} en ${path}: ${body}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // La X-API-Key la pone el proxy del lado del servidor, no acá.
      ...(init?.headers || {}),
    },
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
  /** Renta fija (Tarea 9.4). Precios REALES en pesos, vía IOL. */
  getSenalesBonos: () => request<SenalesBonos>("/senales/bonos"),
  /**
   * Consenso institucional 13F (Tarea 5.5). Es lenta: los filings son
   * trimestrales y la primera llamada de cada trimestre baja todo de SEC EDGAR.
   */
  getSenalesSmartMoney: () =>
    request<SenalesSmartMoney>("/senales/smart-money"),
  /** Saldo y tenencia REAL de IOL (Tarea 8.2). Solo lectura. */
  getSaldoIOL: () => request<SaldoIOL>("/iol/saldo"),
  /** Dólar CCL implícito (Tarea 8.4). Contexto macro, no veta nada. */
  getCcl: () => request<Ccl>("/mercado/ccl"),
  /** Si Google Sheets está configurado y cuántas operaciones faltan subir. */
  getEstadoSheets: () => request<EstadoSheets>("/sync/sheets"),
  /**
   * Espeja a Google Sheets las operaciones cerradas pendientes (Tarea 6.2).
   * Responde 200 aunque falle: el motivo viaja en el cuerpo.
   */
  syncSheets: () => request<SyncSheets>("/sync/sheets", { method: "POST" }),
};
