const KEY = "cane.activeSession";

/**
 * Recuerda SOLO el id de la sesión en curso, para poder continuar tras una
 * recarga. No guarda token, preguntas ni resultados. Es una comodidad por
 * dispositivo: si el almacenamiento no está disponible, simplemente no recuerda.
 */
export interface ActiveSessionStore {
  get(): string | null;
  set(sessionId: string): void;
  clear(): void;
}

export function createActiveSessionStore(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null = safeStorage(),
): ActiveSessionStore {
  return {
    get() {
      try {
        return storage?.getItem(KEY) ?? null;
      } catch {
        return null;
      }
    },
    set(sessionId) {
      try {
        storage?.setItem(KEY, sessionId);
      } catch {
        /* sin almacenamiento: no se recuerda */
      }
    },
    clear() {
      try {
        storage?.removeItem(KEY);
      } catch {
        /* nada que limpiar */
      }
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
