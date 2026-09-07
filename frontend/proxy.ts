import { NextResponse, type NextRequest } from "next/server";
import { COOKIE_SESION, tokenValido } from "@/lib/sesion";

/**
 * Puerta de entrada del dashboard.
 *
 * Publicado en Vercel, el frontend es una URL abierta a internet, y detrás del
 * proxy (`/api/backend`) están el saldo real de la cuenta comitente y el borrado
 * de operaciones. Sin esto, cualquiera que dé con la URL opera el simulador.
 *
 * Falla CERRADA, igual que la API: en producción sin `DASHBOARD_PASSWORD` o sin
 * `SESSION_SECRET` no se atiende nada. Un deploy al que se le olvidó la variable
 * tiene que romperse de forma visible, no quedar abierto en silencio.
 *
 * En desarrollo (`next dev`) sin contraseña configurada, se deja pasar: contra
 * un backend en loopback no aporta nada y molesta en cada recarga.
 */

const RUTAS_PUBLICAS = ["/login", "/api/login"];

export default async function proxy(req: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD;
  const secreto = process.env.SESSION_SECRET;
  const { pathname } = req.nextUrl;

  if (!password || !secreto) {
    if (process.env.NODE_ENV === "development") return NextResponse.next();
    return NextResponse.json(
      {
        detail:
          "El dashboard no tiene DASHBOARD_PASSWORD y SESSION_SECRET configuradas. " +
          "Cargalas en las variables de entorno del deploy (ver frontend/.env.local.example).",
      },
      { status: 503 },
    );
  }

  if (RUTAS_PUBLICAS.some((r) => pathname === r || pathname.startsWith(`${r}/`))) {
    return NextResponse.next();
  }

  if (await tokenValido(req.cookies.get(COOKIE_SESION)?.value, secreto)) {
    return NextResponse.next();
  }

  // El fetch de una página ya cargada tiene que recibir un 401 que la UI pueda
  // mostrar; un redirect a /login le devolvería HTML donde espera JSON.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { detail: "La sesión venció. Recargá la página para volver a entrar." },
      { status: 401 },
    );
  }

  const destino = req.nextUrl.clone();
  destino.pathname = "/login";
  destino.search = "";
  if (pathname !== "/") destino.searchParams.set("volver", pathname);
  return NextResponse.redirect(destino);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
