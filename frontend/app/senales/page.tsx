"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Senales, SenalCandidato } from "@/lib/types";
import { formatNumero, formatFechaHora } from "@/lib/format";

/** Texto que queda guardado como "señal / motivo" de la operación en el simulador. */
function motivoDeCarga(c: SenalCandidato): string {
  return `Señal IA — SL ${formatNumero(c.stop_loss)} / TP ${formatNumero(c.take_profit)} (riesgo ${formatNumero(c.pct_riesgo)}%)`;
}

export default function SenalesPage() {
  const router = useRouter();
  const [data, setData] = useState<Senales | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const escanear = useCallback(() => {
    setCargando(true);
    setError(null);
    api
      .getSenales()
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setCargando(false));
  }, []);

  useEffect(() => {
    escanear();
  }, [escanear]);

  function cargarEnSimulador(c: SenalCandidato) {
    const params = new URLSearchParams({
      ticker: c.ticker,
      precio: String(c.precio_entrada),
      senal: motivoDeCarga(c),
    });
    router.push(`/simulador?${params.toString()}`);
  }

  const vix = data?.vix ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Señales sugeridas</h1>
          <p className="text-sm text-neutral-500">
            Escaneo del universo BYMA con los 7 filtros técnicos, el circuit
            breaker de VIX y el sentimiento de noticias. Solo sugiere: no
            ejecuta ninguna orden.
          </p>
        </div>
        <button
          onClick={escanear}
          disabled={cargando}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
        >
          {cargando ? "Escaneando…" : "Volver a escanear"}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          No se pudo conectar con el backend ({error}).
        </div>
      )}

      {cargando && !data && (
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900">
          Escaneando el universo BYMA… esto puede tardar hasta un minuto: el
          backend consulta precios, noticias y filings de cada ticker.
        </div>
      )}

      {data && (
        <>
          {/* Estado del circuit breaker */}
          {data.veto_global ? (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
              <p className="text-sm font-semibold text-red-800 dark:text-red-200">
                Circuit breaker activo — no se sugieren compras
              </p>
              <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                {data.veto_global}
              </p>
            </div>
          ) : (
            <div className="rounded-lg border border-neutral-200 bg-white p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
              <span className="font-medium">VIX:</span>{" "}
              <span className="text-neutral-600 dark:text-neutral-300">
                {vix?.motivo ?? "—"}
              </span>
              {vix?.vix_actual != null && (
                <span className="ml-2 text-neutral-400">
                  (actual {formatNumero(vix.vix_actual)}, previo{" "}
                  {formatNumero(vix.vix_previo)})
                </span>
              )}
            </div>
          )}

          <p className="text-xs text-neutral-400">
            Escaneo del {formatFechaHora(data.generado)} · {data.universo?.length ?? 0}{" "}
            instrumentos · {data.candidatos.length} válidos ·{" "}
            {data.descartados.length} descartados
          </p>

          {/* Candidatos válidos */}
          <section className="space-y-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
              Señales válidas ({data.candidatos.length})
            </h2>
            <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
              <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                <thead className="bg-neutral-100 dark:bg-neutral-900">
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2">Precio sugerido</th>
                    <th className="px-3 py-2">Stop-loss</th>
                    <th className="px-3 py-2">Take-profit</th>
                    <th className="px-3 py-2">Riesgo</th>
                    <th className="px-3 py-2">Contexto</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                  {data.candidatos.length === 0 && (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-3 py-6 text-center text-neutral-400"
                      >
                        Ninguna señal pasó los filtros en este escaneo.
                      </td>
                    </tr>
                  )}
                  {data.candidatos.map((c) => (
                    <tr
                      key={c.ticker}
                      className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50"
                    >
                      <td className="px-3 py-2 font-medium">{c.ticker}</td>
                      <td className="px-3 py-2">{formatNumero(c.precio_entrada)}</td>
                      <td className="px-3 py-2 text-red-600 dark:text-red-400">
                        {formatNumero(c.stop_loss)}
                      </td>
                      <td className="px-3 py-2 text-emerald-600 dark:text-emerald-400">
                        {formatNumero(c.take_profit)}
                      </td>
                      <td className="px-3 py-2">{formatNumero(c.pct_riesgo)}%</td>
                      {/* Informativo: NO influye en que la señal sea válida. */}
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        <span title="Volumen relativo a las 20 ruedas previas">
                          RVOL {formatNumero(c.rvol)}
                        </span>
                        {c.insiders_detectados && (
                          <span
                            className="ml-1 text-neutral-400"
                            title={c.insiders_detalle ?? undefined}
                          >
                            · insiders
                          </span>
                        )}
                        {c.sentimiento_score != null && (
                          <span className="ml-1 text-neutral-400">
                            · noticias {formatNumero(c.sentimiento_score)}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => cargarEnSimulador(c)}
                          className="text-xs font-medium text-neutral-600 hover:underline dark:text-neutral-300"
                        >
                          Cargar en el simulador
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-neutral-400">
              RVOL, insiders y sentimiento son contexto informativo: no son
              filtros aprobados ni hacen mejor a una señal.
            </p>
          </section>

          {/* Descartados: no se pierden los motivos */}
          <section className="space-y-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
              Descartados ({data.descartados.length})
            </h2>
            <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
              <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                <thead className="bg-neutral-100 dark:bg-neutral-900">
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2">Motivo del veto</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                  {data.descartados.length === 0 && (
                    <tr>
                      <td colSpan={2} className="px-3 py-6 text-center text-neutral-400">
                        No se descartó ningún instrumento.
                      </td>
                    </tr>
                  )}
                  {data.descartados.map((d) => (
                    <tr key={d.ticker}>
                      <td className="px-3 py-2 font-medium text-neutral-500">
                        {d.ticker}
                      </td>
                      <td className="px-3 py-2 text-neutral-500">{d.motivo}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
