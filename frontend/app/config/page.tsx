"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BrokerConfig } from "@/lib/types";
import { formatPct } from "@/lib/format";

export default function ConfigPage() {
  const [cfg, setCfg] = useState<BrokerConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState(false);

  useEffect(() => {
    api.getBrokerConfig().then(setCfg).catch((e) => setError(String(e.message || e)));
  }, []);

  async function save() {
    if (!cfg) return;
    setSaving(true);
    setSavedMsg(false);
    setError(null);
    try {
      const updated = await api.updateBrokerConfig({
        comision_broker: cfg.comision_broker,
        derechos_mercado: cfg.derechos_mercado,
        iva: cfg.iva,
      });
      setCfg(updated);
      setSavedMsg(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        No se pudo conectar con el backend ({error}).
      </div>
    );
  }

  if (!cfg) {
    return <p className="text-sm text-neutral-500">Cargando…</p>;
  }

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Configuración de comisiones</h1>
        <p className="text-sm text-neutral-500">
          Valores estándar del mercado argentino (BYMA / CNV). Ajustalos si tu
          broker o plan cobra distinto.
        </p>
      </div>

      <div className="space-y-4 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <Field
          label="Comisión neta del broker"
          hint="0.50% por cada operación de compra o venta"
          value={cfg.comision_broker}
          onChange={(v) => setCfg({ ...cfg, comision_broker: v })}
        />
        <Field
          label="Derechos de mercado (BYMA)"
          hint="0.08% arancel regulatorio"
          value={cfg.derechos_mercado}
          onChange={(v) => setCfg({ ...cfg, derechos_mercado: v })}
        />
        <Field
          label="IVA sobre comisión y derechos"
          hint="21% de IVA aplicado únicamente sobre los aranceles"
          value={cfg.iva}
          onChange={(v) => setCfg({ ...cfg, iva: v })}
        />

        <div className="rounded-md bg-neutral-100 p-3 text-sm dark:bg-neutral-800">
          <p>
            Costo efectivo por tramo:{" "}
            <span className="font-semibold">
              {formatPct(cfg.costo_efectivo_por_tramo)}
            </span>
          </p>
          <p>
            Costo efectivo total (ida y vuelta):{" "}
            <span className="font-semibold">
              {formatPct(cfg.costo_efectivo_total_ida_y_vuelta)}
            </span>{" "}
            — lo mínimo que debe rendir una posición para no perder dinero.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={saving}
            className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            {saving ? "Guardando…" : "Guardar cambios"}
          </button>
          {savedMsg && (
            <span className="text-sm text-emerald-600 dark:text-emerald-400">
              Guardado.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          step="0.0001"
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          className="w-32 rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-800"
        />
        <span className="text-sm text-neutral-400">
          ({(value * 100).toFixed(2)}%)
        </span>
      </div>
      <p className="mt-1 text-xs text-neutral-400">{hint}</p>
    </div>
  );
}
