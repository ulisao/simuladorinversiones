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

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8123";

/**
 * Clave de la API, que viaja en el header `X-API-Key` en cada request.
 *
 * OJO: al ser `NEXT_PUBLIC_`, Next la incrusta en el bundle del navegador —
 * cualquiera que abra devtools la ve. Es aceptable mientras el frontend corra
 * en la máquina de uno contra un backend en loopback (que es el caso hoy). Si
 * alguna vez este frontend se publica en Vercel, esta clave deja de servir como
 * secreto: ahí hace falta un backend-for-frontend que la guarde del lado del
 * servidor, o login de usuario.
 */
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

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
    return "El backend rechazó la clave. Revisá NEXT_PUBLIC_API_KEY en frontend/.env.local (tiene que coincidir con API_KEY del backend).";
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
      // Solo se manda si está configurada: si el backend corre con
      // API_AUTH_DESHABILITADA=true, un header vacío daría 401 igual.
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
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
