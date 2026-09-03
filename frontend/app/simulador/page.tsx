"use client";

import { Fragment, Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Trade } from "@/lib/types";
import { formatMoney, formatPct } from "@/lib/format";
import NewTradeForm, { type PrefillTrade } from "@/components/NewTradeForm";
import CloseTradeRow from "@/components/CloseTradeRow";

/**
 * La página de Señales navega acá con ?ticker=&precio=&senal= para prellenar el
 * formulario. `useSearchParams` obliga a un Suspense en el App Router.
 */
export default function SimuladorPage() {
  return (
    <Suspense fallback={<p className="text-sm text-neutral-500">Cargando…</p>}>
      <SimuladorContenido />
    </Suspense>
  );
}

function SimuladorContenido() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<number | null>(null);

  const params = useSearchParams();
  const tickerParam = params.get("ticker");
  const precioParam = Number(params.get("precio"));
  const prefill: PrefillTrade | undefined = tickerParam
    ? {
        ticker: tickerParam,
        precio_entrada: Number.isFinite(precioParam) ? precioParam : undefined,
        senal: params.get("senal") ?? "",
      }
    : undefined;

  const reload = useCallback(() => {
    api
      .getTrades()
      .then(setTrades)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function handleDelete(id: number) {
    if (!confirm("¿Eliminar esta operación?")) return;
    await api.deleteTrade(id);
    reload();
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        No se pudo conectar con el backend ({error}).
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Simulador de paper trading</h1>
          <p className="text-sm text-neutral-500">
            Registrá cada señal sugerida para auditar su rentabilidad real,
            neta de comisiones.
          </p>
        </div>
        <NewTradeForm onCreated={reload} prefill={prefill} />
      </div>

      <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
        <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
          <thead className="bg-neutral-100 dark:bg-neutral-900">
            <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Tipo</th>
              <th className="px-3 py-2">F. compra</th>
              <th className="px-3 py-2">Cant.</th>
              <th className="px-3 py-2">P. entrada</th>
              <th className="px-3 py-2">P. salida</th>
              <th className="px-3 py-2">Resultado neto</th>
              <th className="px-3 py-2">Rend. %</th>
              <th className="px-3 py-2">Estado / Señal</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {trades.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-6 text-center text-neutral-400">
                  Todavía no cargaste operaciones.
                </td>
              </tr>
            )}
            {trades.map((t) => (
              <Fragment key={t.id}>
                <tr className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50">
                  <td className="px-3 py-2 font-medium">{t.ticker}</td>
                  <td className="px-3 py-2 text-neutral-500">{t.tipo}</td>
                  <td className="px-3 py-2">{t.fecha_compra}</td>
                  <td className="px-3 py-2">{t.cantidad}</td>
                  <td className="px-3 py-2">{formatMoney(t.precio_entrada)}</td>
                  <td className="px-3 py-2">{formatMoney(t.precio_salida)}</td>
                  <td
                    className={`px-3 py-2 font-medium ${
                      t.resultado_neto == null
                        ? "text-neutral-400"
                        : t.resultado_neto >= 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {formatMoney(t.resultado_neto)}
                  </td>
                  <td className="px-3 py-2">{formatPct(t.rendimiento_neto_pct)}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`mr-1 rounded px-1.5 py-0.5 text-xs font-medium ${
                        t.estado_posicion === "ABIERTA"
                          ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                          : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                      }`}
                    >
                      {t.estado_posicion}
                    </span>
                    <span className="text-neutral-400">{t.senal}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-2">
                      {t.estado_posicion === "ABIERTA" && (
                        <button
                          onClick={() => setClosingId(t.id)}
                          className="text-xs font-medium text-neutral-600 hover:underline dark:text-neutral-300"
                        >
                          Cerrar
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(t.id)}
                        className="text-xs font-medium text-red-500 hover:underline"
                      >
                        Eliminar
                      </button>
                    </div>
                  </td>
                </tr>
                {closingId === t.id && (
                  <CloseTradeRow
                    key={`close-${t.id}`}
                    tradeId={t.id}
                    defaultSenal={t.senal || ""}
                    onClosed={() => {
                      setClosingId(null);
                      reload();
                    }}
                    onCancel={() => setClosingId(null)}
                  />
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
