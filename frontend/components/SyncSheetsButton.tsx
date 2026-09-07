"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EstadoSheets } from "@/lib/types";

/**
 * Botón "Sincronizar con Sheets" (Tarea 6.2).
 *
 * La Fase 6 es opcional: si no hay cuenta de servicio de Google configurada, el
 * backend responde 200 con `configurado: false` y el motivo en castellano. En
 * ese caso el botón se muestra deshabilitado con el motivo, en vez de
 * desaparecer — si el botón no estuviera, no habría forma de darse cuenta de
 * que falta configurar algo.
 */
export default function SyncSheetsButton({
  onSynced,
}: {
  /** Se llama después de una sincronización exitosa, para refrescar la tabla. */
  onSynced?: () => void;
}) {
  const [estado, setEstado] = useState<EstadoSheets | null>(null);
  const [sincronizando, setSincronizando] = useState(false);
  const [aviso, setAviso] = useState<{ ok: boolean; texto: string } | null>(null);

  const cargarEstado = useCallback(() => {
    api
      .getEstadoSheets()
      .then(setEstado)
      .catch(() =>
        // El backend puede estar caído: no es motivo para romper la página.
        setEstado({ configurado: false, pendientes: 0, motivo: "Backend no disponible." }),
      );
  }, []);

  useEffect(() => {
    cargarEstado();
  }, [cargarEstado]);

  async function sincronizar() {
    setSincronizando(true);
    setAviso(null);
    try {
      const r = await api.syncSheets();
      if (r.motivo) {
        setAviso({ ok: false, texto: r.motivo });
      } else if (r.sincronizadas === 0) {
        setAviso({ ok: true, texto: "No había operaciones cerradas pendientes." });
      } else {
        setAviso({
          ok: true,
          texto: `${r.sincronizadas} operación(es) espejadas en Trading_Log_IOL.`,
        });
        onSynced?.();
      }
    } catch (e) {
      setAviso({ ok: false, texto: String((e as Error).message || e) });
    } finally {
      setSincronizando(false);
      cargarEstado();
    }
  }

  const deshabilitado = sincronizando || !estado?.configurado;

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={sincronizar}
        disabled={deshabilitado}
        title={estado?.configurado ? undefined : estado?.motivo}
        className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800"
      >
        {sincronizando ? "Sincronizando…" : "Sincronizar con Sheets"}
        {estado && estado.pendientes > 0 && (
          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-200">
            {estado.pendientes}
          </span>
        )}
      </button>

      {aviso && (
        <p
          className={`max-w-xs text-right text-xs ${
            aviso.ok
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-red-600 dark:text-red-400"
          }`}
        >
          {aviso.texto}
        </p>
      )}

      {!aviso && estado && !estado.configurado && (
        <p className="max-w-xs text-right text-xs text-neutral-400">
          Google Sheets no configurado (Fase 6, opcional).
        </p>
      )}
    </div>
  );
}
