/**
 * Marca persistente de una creación de sesión CON RESULTADO INCIERTO.
 *
 * `POST /sessions` no es idempotente y la API no tiene un endpoint para encontrar una
 * sesión sin conocer su id. Si la respuesta se pierde, la sesión pudo haberse creado y no
 * hay forma determinista de saberlo. Recargar la página o volver a entrar no resuelve eso,
 * así que la marca vive en el almacenamiento del navegador, ligada al usuario.
 *
 * - La clave incluye el id del usuario (el `id` de Supabase Auth): otra cuenta en el mismo
 *   navegador no hereda el bloqueo ni lo confunde.
 * - Solo guarda cuándo ocurrió. Nada de token, sesión, preguntas ni respuestas.
 * - Se escribe ANTES de enviar y se borra solo con un resultado definitivo (sesión creada,
 *   o error HTTP 4xx del servidor). Una recarga con la petición en vuelo deja la marca.
 * - Pasado `UNCERTAIN_HOLD_MS` la marca no se borra sola: hace falta que la persona
 *   reconozca que pudo quedar una sesión sin usar. Un GET (por ejemplo, encontrar una
 *   sesión activa) nunca la borra: no demuestra que sea la de la petición perdida.
 */
const PREFIX = "cane.pendingCreate.v1.";

/** Tiempo durante el cual la petición original aún pudo completarse en el servidor. */
export const UNCERTAIN_HOLD_MS = 10 * 60_000;

export interface PendingCreate {
  /** Momento (ms desde epoch) en que el resultado quedó incierto. */
  at: number;
}

export interface PendingCreateStore {
  get(userId: string): PendingCreate | null;
  /** Marca (o renueva) el resultado incierto de este usuario. */
  set(userId: string): void;
  clear(userId: string): void;
  /** ¿Ya pasó el tiempo en que la petición original pudo completarse? */
  holdElapsed(pending: PendingCreate): boolean;
  /** Hora (ms) a partir de la cual se puede reconocer y continuar. */
  releasableAt(pending: PendingCreate): number;
  /** Cuánto falta (ms) para poder reconocer y continuar; 0 si ya pasó. */
  remainingMs(pending: PendingCreate): number;
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function createPendingCreateStore(
  storage: StorageLike | null = safeStorage(),
  now: () => number = Date.now,
): PendingCreateStore {
  // Respaldo en memoria: si el almacenamiento falla, el bloqueo vale al menos en esta página.
  const memory = new Map<string, PendingCreate>();
  const keyOf = (userId: string) => `${PREFIX}${userId}`;

  return {
    get(userId) {
      try {
        const raw = storage?.getItem(keyOf(userId));
        if (raw) {
          const parsed: unknown = JSON.parse(raw);
          if (
            typeof parsed === "object" && parsed !== null &&
            typeof (parsed as { at?: unknown }).at === "number" &&
            Number.isFinite((parsed as { at: number }).at)
          ) {
            return { at: (parsed as { at: number }).at };
          }
        }
      } catch {
        /* almacenamiento ilegible: se usa el respaldo en memoria */
      }
      return memory.get(userId) ?? null;
    },
    set(userId) {
      const value: PendingCreate = { at: now() };
      memory.set(userId, value);
      try {
        storage?.setItem(keyOf(userId), JSON.stringify(value));
      } catch {
        /* sin almacenamiento: queda el respaldo en memoria */
      }
    },
    clear(userId) {
      memory.delete(userId);
      try {
        storage?.removeItem(keyOf(userId));
      } catch {
        /* nada que limpiar */
      }
    },
    holdElapsed(pending) {
      return now() >= pending.at + UNCERTAIN_HOLD_MS;
    },
    releasableAt(pending) {
      return pending.at + UNCERTAIN_HOLD_MS;
    },
    remainingMs(pending) {
      return Math.max(0, pending.at + UNCERTAIN_HOLD_MS - now());
    },
  };
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
