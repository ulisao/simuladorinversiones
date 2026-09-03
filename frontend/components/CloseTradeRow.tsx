"use client";

import { useState } from "react";
import { api } from "@/lib/api";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function CloseTradeRow({
  tradeId,
  defaultSenal,
  onClosed,
  onCancel,
}: {
  tradeId: number;
  defaultSenal: string;
  onClosed: () => void;
  onCancel: () => void;
}) {
  const [fechaVenta, setFechaVenta] = useState(today());
  const [precioSalida, setPrecioSalida] = useState("");
  const [senal, setSenal] = useState(defaultSenal);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    const precio = parseFloat(precioSalida);
    if (!precio || precio <= 0) {
      setError("Ingresá un precio de salida válido.");
      return;
    }
    setSaving(true);
    try {
      await api.closeTrade(tradeId, {
        fecha_venta: fechaVenta,
        precio_salida: precio,
        senal,
      });
      onClosed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr className="bg-amber-50 dark:bg-amber-950/30">
      <td colSpan={10} className="px-3 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Fecha venta
            </label>
            <input
              type="date"
              value={fechaVenta}
              onChange={(e) => setFechaVenta(e.target.value)}
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Precio salida
            </label>
            <input
              type="number"
              step="any"
              value={precioSalida}
              onChange={(e) => setPrecioSalida(e.target.value)}
              className="w-32 rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
            />
          </div>
          <div className="flex-1 min-w-[10rem]">
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Señal / motivo de salida
            </label>
            <input
              value={senal}
              onChange={(e) => setSenal(e.target.value)}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
            />
          </div>
          <button
            onClick={submit}
            disabled={saving}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            {saving ? "Cerrando…" : "Confirmar cierre"}
          </button>
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            Cancelar
          </button>
        </div>
        {error && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
      </td>
    </tr>
  );
}
