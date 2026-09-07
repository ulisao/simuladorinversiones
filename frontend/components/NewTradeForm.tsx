"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { TradeCreateInput } from "@/lib/types";

const TIPOS = ["CEDEAR", "ACCION", "BONO"];

// Cada estrategia tiene su propio cupo de capital y su propia fila en el
// dashboard (Tarea 5.5), así que hay que saber con cuál se abrió la posición.
const ESTRATEGIAS = [
  { valor: "SWING", etiqueta: "Swing técnico" },
  { valor: "SMART_MONEY", etiqueta: "Smart Money (13F)" },
];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Valores con los que la página de Señales puede prellenar el formulario. */
export interface PrefillTrade {
  ticker?: string;
  precio_entrada?: number;
  senal?: string;
}

export default function NewTradeForm({
  onCreated,
  prefill,
}: {
  onCreated: () => void;
  prefill?: PrefillTrade;
}) {
  // Si venimos desde "Cargar en el simulador", el formulario arranca abierto y
  // con los datos de la señal — pero NO crea nada solo: el usuario confirma.
  const [open, setOpen] = useState(Boolean(prefill?.ticker));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buscandoPrecio, setBuscandoPrecio] = useState(false);
  // Tarea 2.1: el precio de mercado sale de yfinance (acción subyacente en USD),
  // no del CEDEAR en pesos. Se avisa apenas se usa el botón.
  const [avisoPrecio, setAvisoPrecio] = useState<string | null>(null);
  const [form, setForm] = useState<TradeCreateInput>({
    ticker: prefill?.ticker ?? "",
    tipo: "CEDEAR",
    estrategia: "SWING",
    fecha_compra: today(),
    cantidad: 0,
    precio_entrada: prefill?.precio_entrada ?? 0,
    senal: prefill?.senal ?? "",
  });

  async function usarPrecioDeMercado() {
    const ticker = form.ticker.trim();
    if (!ticker) return;
    setError(null);
    setBuscandoPrecio(true);
    try {
      const { precio, advertencia } = await api.getPrecioMercado(ticker);
      setForm((f) => ({ ...f, precio_entrada: precio }));
      setAvisoPrecio(advertencia);
    } catch (err) {
      // El backend devuelve 404 con un detail en español para ticker inválido.
      const bruto = err instanceof Error ? err.message : String(err);
      const detalle = bruto.match(/"detail"\s*:\s*"([^"]+)"/)?.[1];
      setError(detalle ?? `No se pudo obtener el precio de ${ticker}.`);
    } finally {
      setBuscandoPrecio(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.ticker.trim() || form.cantidad <= 0 || form.precio_entrada <= 0) {
      setError("Completá ticker, cantidad y precio de entrada (mayores a 0).");
      return;
    }
    setSaving(true);
    try {
      await api.createTrade(form);
      setForm({
        ticker: "",
        tipo: "CEDEAR",
        estrategia: "SWING",
        fecha_compra: today(),
        cantidad: 0,
        precio_entrada: 0,
        senal: "",
      });
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
      >
        + Nueva operación
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="grid grid-cols-2 gap-3 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 sm:grid-cols-6"
    >
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Ticker
        </label>
        <input
          value={form.ticker}
          onChange={(e) => setForm({ ...form, ticker: e.target.value })}
          placeholder="AAPL"
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Tipo
        </label>
        <select
          value={form.tipo}
          onChange={(e) => setForm({ ...form, tipo: e.target.value })}
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        >
          {TIPOS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Estrategia
        </label>
        <select
          value={form.estrategia}
          onChange={(e) => setForm({ ...form, estrategia: e.target.value })}
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        >
          {ESTRATEGIAS.map((e) => (
            <option key={e.valor} value={e.valor}>
              {e.etiqueta}
            </option>
          ))}
        </select>
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Fecha compra
        </label>
        <input
          type="date"
          value={form.fecha_compra}
          onChange={(e) => setForm({ ...form, fecha_compra: e.target.value })}
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Cantidad
        </label>
        <input
          type="number"
          step="any"
          value={form.cantidad || ""}
          onChange={(e) =>
            setForm({ ...form, cantidad: parseFloat(e.target.value) || 0 })
          }
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Precio entrada
        </label>
        <input
          type="number"
          step="any"
          value={form.precio_entrada || ""}
          onChange={(e) =>
            setForm({ ...form, precio_entrada: parseFloat(e.target.value) || 0 })
          }
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
        <button
          type="button"
          onClick={usarPrecioDeMercado}
          disabled={!form.ticker.trim() || buscandoPrecio}
          className="mt-1 text-xs font-medium text-neutral-600 underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-neutral-300 dark:text-neutral-300 dark:disabled:text-neutral-600"
        >
          {buscandoPrecio ? "Buscando…" : "Usar precio de mercado"}
        </button>
        {avisoPrecio && (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
            {avisoPrecio}
          </p>
        )}
      </div>
      <div className="col-span-1">
        <label className="mb-1 block text-xs font-medium text-neutral-500">
          Señal / motivo
        </label>
        <input
          value={form.senal}
          onChange={(e) => setForm({ ...form, senal: e.target.value })}
          placeholder="Ruptura alcista"
          className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
      </div>

      {error && (
        <p className="col-span-full text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="col-span-full flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900"
        >
          {saving ? "Guardando…" : "Guardar operación"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-md px-4 py-1.5 text-sm font-medium text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}
