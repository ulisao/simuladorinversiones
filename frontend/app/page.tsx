"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Dashboard, SaldoIOL, Ccl } from "@/lib/types";
import { formatMoney, formatNumero, formatPct } from "@/lib/format";
import MetricCard from "@/components/MetricCard";

/** Nombres legibles de las estrategias (Tarea 5.5). */
const NOMBRE_ESTRATEGIA: Record<string, string> = {
  SWING: "Swing técnico",
  SMART_MONEY: "Smart Money (13F)",
};

const DETALLE_ESTRATEGIA: Record<string, string> = {
  SWING: "7 filtros técnicos y RSI de sobreventa",
  SMART_MONEY: "Consenso de fondos institucionales",
};

/** Accesos directos a las otras páginas, en el orden del flujo de trabajo. */
const ACCESOS = [
  {
    href: "/senales",
    titulo: "Señales",
    descripcion: "Escanear el mercado y ver qué pasa los filtros",
    paso: "1",
  },
  {
    href: "/simulador",
    titulo: "Simulador",
    descripcion: "Cargar operaciones y cerrarlas cuando terminan",
    paso: "2",
  },
  {
    href: "/config",
    titulo: "Configuración",
    descripcion: "Comisiones del broker (recalcula todo el histórico)",
    paso: "3",
  },
];

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Cuenta real de IOL (Tareas 8.2 y 8.4). Van aparte del dashboard a propósito:
  // si IOL está caído, el paper trading tiene que seguir mostrándose igual.
  const [saldo, setSaldo] = useState<SaldoIOL | null>(null);
  const [ccl, setCcl] = useState<Ccl | null>(null);
  const [errorIol, setErrorIol] = useState<string | null>(null);

  useEffect(() => {
    api
      .getDashboard()
      .then(setData)
      .catch((e) => setError(String(e.message || e)));

    api.getSaldoIOL().then(setSaldo).catch((e) => setErrorIol(String(e.message || e)));
    api.getCcl().then(setCcl).catch(() => setCcl(null));
  }, []);

  // Las métricas dependen del backend, pero los accesos a las otras páginas no:
  // se renderizan siempre, incluso con la API caída — que es justo cuando hace
  // falta poder irse a otra pantalla.
  const esRentable = data ? data.ganancia_perdida_neta_total > 0 : false;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Dashboard cuantitativo</h1>
        <p className="text-sm text-neutral-500">
          Métricas consolidadas para saber si el modelo gana o pierde plata en
          la práctica, neto de comisiones.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {ACCESOS.map((a) => (
          <Link
            key={a.href}
            href={a.href}
            className="group rounded-lg border border-neutral-200 bg-white p-4 shadow-sm transition-colors hover:border-neutral-400 hover:bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900 dark:hover:border-neutral-600 dark:hover:bg-neutral-800"
          >
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold">
                <span className="mr-1.5 text-xs font-normal text-neutral-400">
                  {a.paso}
                </span>
                {a.titulo}
              </p>
              <span
                aria-hidden="true"
                className="text-neutral-300 transition-transform group-hover:translate-x-0.5 dark:text-neutral-600"
              >
                →
              </span>
            </div>
            <p className="mt-1 text-xs text-neutral-500">{a.descripcion}</p>
          </Link>
        ))}
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          No se pudo conectar con el backend ({error}). Revisá que esté corriendo
          en la URL configurada en NEXT_PUBLIC_API_URL.
        </div>
      )}

      {!error && !data && (
        <p className="text-sm text-neutral-500">Cargando…</p>
      )}

      {/* CUENTA REAL — Tareas 8.2 y 8.4. Borde ámbar y leyenda explícita para que
          nunca se confunda plata real con las métricas de paper trading. */}
      <section className="rounded-lg border-2 border-amber-400 bg-amber-50/50 p-4 dark:border-amber-600 dark:bg-amber-950/20">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
            💰 Cuenta real — IOL
          </h2>
          {ccl && (
            <span
              className="text-xs text-amber-700 dark:text-amber-400"
              title={`${ccl.bono_pesos} $${ccl.precio_pesos} / ${ccl.bono_dolares} US$${ccl.precio_dolares}`}
            >
              Dólar CCL {formatMoney(ccl.ccl)}
            </span>
          )}
        </div>

        {errorIol && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            No se pudo consultar IOL ({errorIol}). El paper trading de abajo no
            se ve afectado.
          </p>
        )}

        {!errorIol && !saldo && (
          <p className="text-xs text-amber-700 dark:text-amber-400">Consultando IOL…</p>
        )}

        {saldo && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <p className="text-xs text-neutral-500">Disponible para operar</p>
                <p className="text-lg font-semibold">{formatMoney(saldo.disponible)}</p>
              </div>
              <div>
                <p className="text-xs text-neutral-500">Títulos valorizados</p>
                <p className="text-lg font-semibold">
                  {formatMoney(saldo.titulos_valorizados)}
                </p>
              </div>
              <div>
                <p className="text-xs text-neutral-500">Total en la cuenta</p>
                <p className="text-lg font-semibold">{formatMoney(saldo.total)}</p>
              </div>
            </div>

            {saldo.posiciones.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
                  Ver las {saldo.posiciones.length} posiciones reales en cartera
                </summary>
                <div className="mt-2 overflow-x-auto">
                  <table className="min-w-full text-xs">
                    <thead className="text-left text-neutral-500">
                      <tr>
                        <th className="py-1 pr-3">Símbolo</th>
                        <th className="py-1 pr-3">Cantidad</th>
                        <th className="py-1 pr-3">PPC</th>
                        <th className="py-1 pr-3">Último</th>
                        <th className="py-1 pr-3">Valorizado</th>
                        <th className="py-1">Ganancia</th>
                      </tr>
                    </thead>
                    <tbody>
                      {saldo.posiciones.map((pos) => (
                        <tr key={pos.simbolo ?? Math.random()}>
                          <td className="py-1 pr-3 font-medium">{pos.simbolo}</td>
                          <td className="py-1 pr-3">{formatNumero(pos.cantidad)}</td>
                          <td className="py-1 pr-3">
                            {formatNumero(pos.precio_promedio_compra)}
                          </td>
                          <td className="py-1 pr-3">{formatNumero(pos.ultimo_precio)}</td>
                          <td className="py-1 pr-3">{formatMoney(pos.valorizado)}</td>
                          <td
                            className={`py-1 ${
                              pos.ganancia_dinero >= 0
                                ? "text-emerald-600 dark:text-emerald-400"
                                : "text-red-600 dark:text-red-400"
                            }`}
                          >
                            {formatMoney(pos.ganancia_dinero)} ({formatNumero(pos.ganancia_pct)}%)
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </>
        )}
        <p className="mt-3 text-xs text-neutral-500">
          Solo lectura. El sistema <strong>no envía órdenes</strong>: el kill
          switch <code>MODO_FANTASMA</code> está activo.
        </p>
      </section>

      {data && (
        <>
          <div className="border-t border-neutral-200 pt-4 dark:border-neutral-800">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
              Paper trading (simulado)
            </h2>
          </div>
          <div
            className={`rounded-lg border p-4 text-center text-sm font-semibold ${
              esRentable
                ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
                : "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
            }`}
          >
            {data.veredicto}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <MetricCard
              label="Capital total invertido"
              value={formatMoney(data.capital_total_invertido)}
              hint="Acumulado en compras simuladas"
            />
            <MetricCard
              label="Comisiones pagadas"
              value={formatMoney(data.total_comisiones_pagadas)}
              hint="Fricción total (broker + BYMA + IVA)"
            />
            <MetricCard
              label="Ganancia / pérdida neta"
              value={formatMoney(data.ganancia_perdida_neta_total)}
              tone={esRentable ? "good" : "bad"}
              hint="Dinero real ganado o perdido"
            />
            <MetricCard
              label="Rentabilidad neta ponderada"
              value={formatPct(data.rentabilidad_neta_ponderada_pct)}
              tone={esRentable ? "good" : "bad"}
            />
            <MetricCard
              label="Operaciones cerradas"
              value={String(data.total_operaciones_ejecutadas)}
              hint={`${data.operaciones_ganadoras} ganadoras · ${data.operaciones_perdedoras} perdedoras`}
            />
            <MetricCard
              label="Tasa de acierto (win rate)"
              value={formatPct(data.tasa_acierto_pct)}
            />
          </div>

          {/* Tarea 5.5: cada estrategia tiene su propio cupo de capital, así que
              mezclar sus resultados en un solo número haría imposible saber cuál
              de las dos rinde. */}
          {data.por_estrategia?.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
                Por estrategia
              </h2>
              <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
                <table className="min-w-full divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
                  <thead className="bg-neutral-100 dark:bg-neutral-900">
                    <tr className="text-left text-xs font-medium uppercase tracking-wide text-neutral-500">
                      <th className="px-3 py-2">Estrategia</th>
                      <th className="px-3 py-2">Cupo</th>
                      <th className="px-3 py-2">Invertido</th>
                      <th className="px-3 py-2">Resultado neto</th>
                      <th className="px-3 py-2">Rentabilidad</th>
                      <th className="px-3 py-2">Cerradas</th>
                      <th className="px-3 py-2">Acierto</th>
                      <th className="px-3 py-2">Abiertas</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                    {data.por_estrategia.map((e) => {
                      const gana = e.ganancia_perdida_neta_total > 0;
                      const pierde = e.ganancia_perdida_neta_total < 0;
                      const tono = gana
                        ? "text-emerald-600 dark:text-emerald-400"
                        : pierde
                          ? "text-red-600 dark:text-red-400"
                          : "text-neutral-500";
                      return (
                        <tr
                          key={e.estrategia}
                          className="hover:bg-neutral-50 dark:hover:bg-neutral-900/50"
                        >
                          <td className="px-3 py-2">
                            <span className="font-medium">
                              {NOMBRE_ESTRATEGIA[e.estrategia] ?? e.estrategia}
                            </span>
                            <span className="ml-2 text-xs text-neutral-400">
                              {DETALLE_ESTRATEGIA[e.estrategia] ?? ""}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-neutral-500">
                            {formatMoney(e.cupo_asignado)}
                          </td>
                          <td className="px-3 py-2">
                            {formatMoney(e.capital_total_invertido)}
                          </td>
                          <td className={`px-3 py-2 font-medium ${tono}`}>
                            {formatMoney(e.ganancia_perdida_neta_total)}
                          </td>
                          <td className={`px-3 py-2 ${tono}`}>
                            {formatPct(e.rentabilidad_neta_ponderada_pct)}
                          </td>
                          <td className="px-3 py-2">
                            {e.total_operaciones_ejecutadas}
                            <span className="ml-1 text-xs text-neutral-400">
                              ({e.operaciones_ganadoras}G / {e.operaciones_perdedoras}P)
                            </span>
                          </td>
                          <td className="px-3 py-2">{formatPct(e.tasa_acierto_pct)}</td>
                          <td className="px-3 py-2">{e.posiciones_abiertas}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-neutral-400">
                El cupo sale de <code>backend/app/config.py</code> y está
                documentado en <code>docs/parametros-riesgo.md</code>. Una
                estrategia con cupo y cero operaciones todavía no operó.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
