"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { formatMoney, formatPct } from "@/lib/format";
import MetricCard from "@/components/MetricCard";

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

  useEffect(() => {
    api
      .getDashboard()
      .then(setData)
      .catch((e) => setError(String(e.message || e)));
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

      {data && (
        <>
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
        </>
      )}
    </div>
  );
}
