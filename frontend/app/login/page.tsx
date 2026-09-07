"use client";

import { useState } from "react";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const cuerpo: unknown = await res.json().catch(() => null);
        const detalle =
          cuerpo && typeof cuerpo === "object"
            ? (cuerpo as { detail?: unknown }).detail
            : null;
        setError(typeof detalle === "string" ? detalle : "No se pudo entrar.");
        setEnviando(false);
        return;
      }
      // Recarga completa a propósito: el middleware tiene que ver la cookie
      // nueva, y el router de Next puede servir la página vieja desde su caché.
      const volver = new URLSearchParams(window.location.search).get("volver");
      window.location.href = volver && volver.startsWith("/") ? volver : "/";
    } catch {
      setError("No se pudo contactar al servidor.");
      setEnviando(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm py-12">
      <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
        Dashboard privado
      </h1>
      <p className="mt-1 text-sm text-neutral-500">
        Simulador de Inversiones IA — paper trading, sin dinero real.
      </p>

      <form onSubmit={entrar} className="mt-6 space-y-3">
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Contraseña"
          autoFocus
          autoComplete="current-password"
          className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 outline-none focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:focus:border-neutral-400"
        />
        <button
          type="submit"
          disabled={enviando || password.length === 0}
          className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
        >
          {enviando ? "Entrando…" : "Entrar"}
        </button>
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
      </form>
    </div>
  );
}
