const REQUEST_TIMEOUT_MS = 15_000;

export type HealthResult =
  | { status: "ok" }
  | {
      status: "error";
      kind: "config" | "network" | "timeout" | "http" | "invalid";
      message: string;
    };

/** URL base del backend, sin barra final. `undefined` si no está configurada. */
export function getApiUrl(): string | undefined {
  const raw = import.meta.env.VITE_API_URL?.trim();
  return raw ? raw.replace(/\/+$/, "") : undefined;
}

/** Consulta GET /health. Nunca lanza: los fallos se devuelven como resultado. */
export async function checkHealth(): Promise<HealthResult> {
  const baseUrl = getApiUrl();
  if (!baseUrl) {
    return {
      status: "error",
      kind: "config",
      message:
        "VITE_API_URL no está configurada. Copia frontend/.env.example a frontend/.env.",
    };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${baseUrl}/health`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      return {
        status: "error",
        kind: "http",
        message: `El backend respondió con HTTP ${response.status}.`,
      };
    }
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      (body as { ok?: unknown }).ok === true
    ) {
      return { status: "ok" };
    }
    return {
      status: "error",
      kind: "invalid",
      message: "La respuesta de /health no tiene el formato esperado.",
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return {
        status: "error",
        kind: "timeout",
        message: `El backend no respondió en ${REQUEST_TIMEOUT_MS / 1000} s.`,
      };
    }
    if (error instanceof SyntaxError) {
      return {
        status: "error",
        kind: "invalid",
        message: "La respuesta de /health no es JSON válido.",
      };
    }
    return {
      status: "error",
      kind: "network",
      message: `No se pudo contactar al backend en ${baseUrl}. ¿Está en ejecución?`,
    };
  } finally {
    clearTimeout(timer);
  }
}
