/**
 * Sesión del dashboard: un token firmado guardado en una cookie httpOnly.
 *
 * Es deliberadamente mínimo — no hay usuarios, hay UNA contraseña compartida
 * (`DASHBOARD_PASSWORD`). Lo único que tiene que garantizar es que nadie pueda
 * fabricarse la cookie sin conocerla.
 *
 * Usa Web Crypto y no `node:crypto` porque el middleware corre en el runtime
 * Edge, donde `node:crypto` no existe.
 */

export const COOKIE_SESION = "sesion_dashboard";

/** Una semana. Es un dashboard personal, no hace falta pedirla todos los días. */
export const DURACION_SESION_MS = 7 * 24 * 60 * 60 * 1000;

const encoder = new TextEncoder();

async function firmar(dato: string, secreto: string): Promise<string> {
  const clave = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secreto),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const firma = await crypto.subtle.sign("HMAC", clave, encoder.encode(dato));
  return Array.from(new Uint8Array(firma))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Comparación de tiempo constante. Con `===` el tiempo de respuesta filtra
 * cuántos caracteres del principio acertó quien está probando.
 */
function igualesEnTiempoConstante(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let dif = 0;
  for (let i = 0; i < a.length; i++) {
    dif |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return dif === 0;
}

/** Token con forma `<vencimiento>.<firma>`. */
export async function crearToken(secreto: string): Promise<string> {
  const vence = Date.now() + DURACION_SESION_MS;
  return `${vence}.${await firmar(String(vence), secreto)}`;
}

export async function tokenValido(
  token: string | undefined,
  secreto: string,
): Promise<boolean> {
  if (!token) return false;
  const [vence, firma] = token.split(".");
  if (!vence || !firma) return false;
  if (!/^\d+$/.test(vence) || Number(vence) < Date.now()) return false;
  return igualesEnTiempoConstante(firma, await firmar(vence, secreto));
}

/** La contraseña también se compara por firma, para no filtrar tiempos. */
export async function passwordCorrecta(
  ingresada: string,
  esperada: string,
  secreto: string,
): Promise<boolean> {
  const [a, b] = await Promise.all([
    firmar(ingresada, secreto),
    firmar(esperada, secreto),
  ]);
  return igualesEnTiempoConstante(a, b);
}
