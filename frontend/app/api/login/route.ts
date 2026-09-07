import { NextResponse, type NextRequest } from "next/server";
import {
  COOKIE_SESION,
  DURACION_SESION_MS,
  crearToken,
  passwordCorrecta,
} from "@/lib/sesion";

/**
 * Entrada y salida del dashboard. Una sola contraseña compartida, sin usuarios.
 * La cookie es httpOnly: el JavaScript de la página no puede leerla.
 */

export async function POST(req: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD;
  const secreto = process.env.SESSION_SECRET;
  if (!password || !secreto) {
    return NextResponse.json(
      {
        detail:
          "El dashboard no tiene DASHBOARD_PASSWORD y SESSION_SECRET configuradas.",
      },
      { status: 503 },
    );
  }

  let ingresada = "";
  try {
    const cuerpo: unknown = await req.json();
    if (cuerpo && typeof cuerpo === "object") {
      const valor = (cuerpo as { password?: unknown }).password;
      if (typeof valor === "string") ingresada = valor;
    }
  } catch {
    // Cuerpo inválido: se trata como contraseña vacía y cae en el 401 de abajo.
  }

  if (!(await passwordCorrecta(ingresada, password, secreto))) {
    return NextResponse.json({ detail: "Contraseña incorrecta." }, { status: 401 });
  }

  // `secure` se decide por el host y no por NODE_ENV: un `next start` local
  // corre en producción sobre http, y una cookie Secure ahí el navegador no la
  // devuelve nunca — quedaría un loop de login imposible de diagnosticar.
  const host = req.nextUrl.hostname;
  const esLocal = host === "localhost" || host === "127.0.0.1" || host === "::1";

  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_SESION, await crearToken(secreto), {
    httpOnly: true,
    sameSite: "lax",
    secure: !esLocal,
    path: "/",
    maxAge: DURACION_SESION_MS / 1000,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_SESION, "", { path: "/", maxAge: 0 });
  return res;
}

export const dynamic = "force-dynamic";
