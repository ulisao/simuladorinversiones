"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Senales, SenalCandidato, SenalesBonos, SenalBono } from "@/lib/types";
import { formatMoney, formatNumero, formatFechaHora } from "@/lib/format";

/** Texto que queda guardado como "señal / motivo" de la operación en el simulador. */
// Etiquetas del origen de la señal (Tarea 3.7). Las dos fuentes conviven: la
// idea es poder comparar en el simulador cuál rinde mejor.
const ETIQUETA_ORIGEN: Record<string, string> = {
  "7_FILTROS": "7 filtros",
  RSI: "RSI",
  AMBOS: "Ambos",
};

const TITULO_ORIGEN: Record<string, string> = {
  "7_FILTROS": "Tendencia + fuerza relativa + ATR (Fase 3)",
  RSI: "RSI(14) por debajo de 30: sobreventa",
  AMBOS: "Las dos fuentes coincidieron en este ticker",
};

const ESTILO_ORIGEN: Record<string, string> = {
  "7_FILTROS":
    "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  RSI: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  AMBOS: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
};

function motivoDeCarga(c: SenalCandidato): string {
  // El origen queda grabado en la operación: es lo que después permite comparar
  // en el dashboard qué fuente de señal rindió mejor (Tarea 3.7).
  const origen = ETIQUETA_ORIGEN[c.origen] ?? c.origen;
  return `Señal IA (${origen}) — SL ${formatNumero(c.stop_loss)} / TP ${formatNumero(c.take_profit)} (riesgo ${formatNumero(c.pct_riesgo)}%)`;
}

export default function SenalesPage() {
  const router = useRouter();
  // Dos universos con fuentes de precio distintas (Tarea 9.4): los CEDEARs usan
  // yfinance (subyacente en USD) y los bonos IOL (precio real en pesos). Se
  // escanean por separado para que uno caído no se lleve puesto al otro.
  const [pestana, setPestana] = useState<"cedears" | "bonos">("cedears");

  const [data, setData] = useState<Senales | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [bonos, setBonos] = useState<SenalesBonos | null>(null);
  const [cargandoBonos, setCargandoBonos] = useState(false);
  const [errorBonos, setErrorBonos] = useState<string | null>(null);

  const escanear = useCallback(() => {
    setCargando(true);
    setError(null);
    api
      .getSenales()
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setCargando(false));
  }, []);

  const escanearBonos = useCallback(() => {
    setCargandoBonos(true);
    setErrorBonos(null);
    api
      .getSenalesBonos()
      .then(setBonos)
      .catch((e) => setErrorBonos(String(e?.message ?? e)))
      .finally(() => setCargandoBonos(false));
  }, []);

  useEffect(() => {
    escanear();
  }, [escanear]);

  // Los bonos se piden recién al abrir su pestaña: el escaneo carga FinBERT y
  // consulta IOL bono por bono, y no tiene sentido pagar eso si nadie lo mira.
  useEffect(() => {
    if (pestana === "bonos" && !bonos && !cargandoBonos && !errorBonos) {
      escanearBonos();
    }
  }, [pestana, bonos, cargandoBonos, errorBonos, escanearBonos]);

  function cargarBonoEnSimulador(b: SenalBono) {
    const params = new URLSearchParams({
      ticker: b.simbolo,
      precio: String(b.precio_entrada),
      senal: `Señal bono — SL ${formatNumero(b.stop_loss)} / TP ${formatNumero(b.take_profit)} (riesgo ${formatNumero(b.pct_riesgo)}%)`,
    });
    router.push(`/simulador?${params.toString()}`);
  }

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
          onClick={pestana === "cedears" ? escanear : escanearBonos}
          disabled={pestana === "cedears" ? cargando : cargandoBonos}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
        >
          {(pestana === "cedears" ? cargando : cargandoBonos)
            ? "Escaneando…"
            : "Volver a escanear"}
        </button>
      </div>

      {/* Pestañas: CEDEARs vs bonos (Tarea 9.4) */}
      <div className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
        {([
          ["cedears", "CEDEARs y acciones"],
          ["bonos", "Bonos"],
        ] as const).map(([clave, etiqueta]) => (
          <button
            key={clave}
            onClick={() => setPestana(clave)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              pestana === clave
                ? "border-neutral-900 text-neutral-900 dark:border-white dark:text-white"
                : "border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
            }`}
          >
            {etiqueta}
          </button>
        ))}
      </div>

      {/* ---------- Pestaña de CEDEARs ---------- */}
      {pestana === "cedears" && (
        <>
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

            {/* Tarea 2.1: el precio viene de yfinance (acción subyacente en USD),
                no del CEDEAR en pesos. No se puede usar para calcular cantidades. */}
            {data.advertencia_precios && (
              <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
                <span className="font-semibold">Precios de referencia:</span>{" "}
                {data.advertencia_precios}
              </p>
            )}

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
                      <th className="px-3 py-2">Origen</th>
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
                          colSpan={8}
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
                        <td className="px-3 py-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                              ESTILO_ORIGEN[c.origen] ?? ESTILO_ORIGEN["7_FILTROS"]
                            }`}
                            title={TITULO_ORIGEN[c.origen] ?? c.origen}
                          >
                            {ETIQUETA_ORIGEN[c.origen] ?? c.origen}
                          </span>
                        </td>
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
                          {c.rsi != null && (
                            <span className="ml-1 text-neutral-400" title="RSI(14)">
                              · RSI {formatNumero(c.rsi)}
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
        </>
      )}

      {/* ---------- Pestaña de bonos (Tarea 9.4) ---------- */}
      {pestana === "bonos" && (
        <>
          {errorBonos && (
            <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
              No se pudo escanear bonos ({errorBonos}).
            </div>
          )}

          {cargandoBonos && !bonos && (
            <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900">
              Escaneando renta fija… el backend consulta la cotización real de
              cada bono en IOL y el sentimiento de noticias de deuda.
            </div>
          )}

          {bonos && (
            <>
              {bonos.veto_global ? (
                <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
                  <p className="text-sm font-semibold text-red-800 dark:text-red-200">
                    Escaneo de bonos bloqueado
                  </p>
                  <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                    {bonos.veto_global}
                  </p>
                </div>
              ) : (
                <p className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                  <span className="font-semibold">Precios reales:</span>{" "}
                  {bonos.nota_precios}
                </p>
              )}

              <p className="text-xs text-neutral-400">
                Escaneo del {formatFechaHora(bonos.generado)} ·{" "}
                {bonos.universo.length} bonos · {bonos.candidatos.length} válidos ·{" "}
                {bonos.descartados.length} descartados
              </p>

              <section className="space-y-2">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
                  Señales de renta fija ({bonos.candidatos.length})
                </h2>
                <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
                  <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                    <thead className="bg-neutral-100 dark:bg-neutral-900">
                      <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
                        <th className="px-3 py-2">Bono</th>
                        <th className="px-3 py-2">Tipo</th>
                        <th className="px-3 py-2">Precio</th>
                        <th className="px-3 py-2">Stop-loss</th>
                        <th className="px-3 py-2">Take-profit</th>
                        <th className="px-3 py-2">Riesgo</th>
                        <th className="px-3 py-2">Contexto</th>
                        <th className="px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                      {bonos.candidatos.length === 0 && (
                        <tr>
                          <td colSpan={8} className="px-3 py-6 text-center text-neutral-400">
                            Ningún bono pasó los filtros en este escaneo.
                          </td>
                        </tr>
                      )}
                      {bonos.candidatos.map((b) => (
                        <tr
                          key={b.simbolo}
                          className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50"
                        >
                          <td className="px-3 py-2 font-medium">{b.simbolo}</td>
                          <td className="px-3 py-2 text-xs text-neutral-500">{b.tipo}</td>
                          <td className="px-3 py-2">{formatMoney(b.precio_entrada)}</td>
                          <td className="px-3 py-2 text-red-600 dark:text-red-400">
                            {formatNumero(b.stop_loss)}
                          </td>
                          <td className="px-3 py-2 text-emerald-600 dark:text-emerald-400">
                            {formatNumero(b.take_profit)}
                          </td>
                          <td className="px-3 py-2">{formatNumero(b.pct_riesgo)}%</td>
                          <td className="px-3 py-2 text-xs text-neutral-500">
                            {b.sentimiento_score != null && (
                              <span title={b.sentimiento_motivo ?? undefined}>
                                noticias {formatNumero(b.sentimiento_score)}
                              </span>
                            )}
                            {/* El spread solo se puede medir en horario de rueda:
                                fuera de rueda IOL devuelve el libro vacío. */}
                            <span
                              className="ml-1 text-neutral-400"
                              title={b.spread_nota ?? undefined}
                            >
                              · spread{" "}
                              {b.spread_disponible ? `${formatNumero(b.spread_pct)}%` : "s/d"}
                            </span>
                            {b.datos_limitados && (
                              <span
                                className="ml-1 text-amber-600 dark:text-amber-400"
                                title="Yahoo no tiene serie de este bono: el stop cae al tope estricto de config"
                              >
                                · datos limitados
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <button
                              onClick={() => cargarBonoEnSimulador(b)}
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
              </section>

              {bonos.descartados.length > 0 && (
                <section className="space-y-2">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
                    Descartados ({bonos.descartados.length})
                  </h2>
                  <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
                    <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                      <thead className="bg-neutral-100 dark:bg-neutral-900">
                        <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
                          <th className="px-3 py-2">Bono</th>
                          <th className="px-3 py-2">Etapa</th>
                          <th className="px-3 py-2">Motivo del veto</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                        {bonos.descartados.map((d) => (
                          <tr key={`${d.simbolo}-${d.etapa}`}>
                            <td className="px-3 py-2 font-medium text-neutral-500">
                              {d.simbolo}
                            </td>
                            <td className="px-3 py-2 text-xs text-neutral-400">{d.etapa}</td>
                            <td className="px-3 py-2 text-neutral-500">{d.motivo}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
