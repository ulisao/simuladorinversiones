import { NextResponse, type NextRequest } from "next/server";

/**
 * Proxy del navegador hacia la API FastAPI.
 *
 * Existe por una razón concreta: la `X-API-Key` NO puede vivir en el bundle del
 * navegador. Antes viajaba como `NEXT_PUBLIC_API_KEY`, y Next incrusta esas
 * variables en el JavaScript que se descarga el cliente — publicado en Vercel,
 * eso es publicar la clave. Acá la clave se queda del lado del servidor de Next
 * y el browser nunca la ve.
 *
 * De paso resuelve el CORS: el request contra el backend lo hace el servidor,
 * no el navegador, así que `CORS_ORIGINS` del backend no necesita conocer el
 * dominio de Vercel.
 *
 * Quién puede llegar a este proxy lo decide `proxy.ts`.
 */

const BACKEND_URL = (
  process.env.BACKEND_URL || "http://127.0.0.1:8123"
).replace(/\/+$/, "");
const BACKEND_API_KEY = process.env.BACKEND_API_KEY || "";

async function proxy(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  const destino = `${BACKEND_URL}/${path.join("/")}${req.nextUrl.search}`;

  // Solo se reenvía lo indispensable. Reenviar los headers del browser tal cual
  // arrastraría cookies y Authorization hacia el backend sin necesidad.
  const headers: Record<string, string> = {};
  const contentType = req.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  if (BACKEND_API_KEY) headers["X-API-Key"] = BACKEND_API_KEY;

  const sinCuerpo = req.method === "GET" || req.method === "HEAD";

  let res: Response;
  try {
    res = await fetch(destino, {
      method: req.method,
      headers,
      body: sinCuerpo ? undefined : await req.text(),
      cache: "no-store",
    });
  } catch {
    // El backend escucha en loopback detrás del túnel: si el túnel se cayó, esto
    // es lo que ve el usuario. Mejor un mensaje que un stack de fetch.
    return NextResponse.json(
      {
        detail:
          "No se pudo contactar al backend. Revisá que el túnel esté levantado " +
          "y que BACKEND_URL apunte al lugar correcto.",
      },
      { status: 502 },
    );
  }

  const cuerpo = await res.text();
  return new NextResponse(cuerpo || null, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

/** Nada de esto se cachea: son precios y saldos. */
export const dynamic = "force-dynamic";
