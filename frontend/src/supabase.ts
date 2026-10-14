/**
 * Supabase SOLO para autenticación. Este módulo no usa tablas, RPC ni
 * almacenamiento: el contenido del juego pasa por la API (ver api.ts).
 */
import { createClient } from "@supabase/supabase-js";

export type SignInResult = { ok: true } | { ok: false; message: string };

export interface AuthService {
  signIn(email: string, password: string): Promise<SignInResult>;
  signOut(): Promise<void>;
  /** Token de acceso vigente (el SDK lo renueva solo) o null sin sesión. */
  getAccessToken(): Promise<string | null>;
  /** Id del usuario con sesión (el de Supabase Auth) o null. No devuelve ni guarda el token. */
  getUserId(): Promise<string | null>;
  /** Avisa cuando la sesión termina (cierre, vencimiento no renovable). */
  onSignedOut(callback: () => void): () => void;
}

export function createAuthService(url: string, publishableKey: string): AuthService {
  const client = createClient(url, publishableKey, {
    auth: { persistSession: true, autoRefreshToken: true },
  });

  return {
    async signIn(email, password) {
      try {
        const { error } = await client.auth.signInWithPassword({ email, password });
        if (!error) return { ok: true };
        if (error.status === 400 || /invalid login credentials/i.test(error.message)) {
          return { ok: false, message: "Correo o contraseña incorrectos." };
        }
        if (/email not confirmed/i.test(error.message)) {
          return { ok: false, message: "Tu correo aún no está confirmado. Avisa al administrador." };
        }
        return { ok: false, message: "No se pudo iniciar sesión. Intenta de nuevo." };
      } catch {
        return { ok: false, message: "No se pudo conectar con el servicio de acceso." };
      }
    },
    async signOut() {
      try {
        await client.auth.signOut();
      } catch {
        /* sin red: la sesión local igualmente se descarta */
      }
    },
    async getAccessToken() {
      try {
        const { data } = await client.auth.getSession();
        return data.session?.access_token ?? null;
      } catch {
        return null;
      }
    },
    async getUserId() {
      try {
        const { data } = await client.auth.getSession();
        return data.session?.user.id ?? null;
      } catch {
        return null;
      }
    },
    onSignedOut(callback) {
      const { data } = client.auth.onAuthStateChange((event) => {
        if (event === "SIGNED_OUT") callback();
      });
      return () => data.subscription.unsubscribe();
    },
  };
}
