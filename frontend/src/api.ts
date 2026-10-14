import type {
  AnswerInput,
  Attempt,
  CreateSessionInput,
  Question,
  RankingRow,
  Session,
} from "./types";

const REQUEST_TIMEOUT_MS = 15_000;
/**
 * Espera larga, solo para operaciones seguras cuando el servidor pudo dormirse (el plan
 * gratuito de Render duerme tras 15 min sin tráfico y tarda ~1 min en despertar).
 */
export const PATIENT_TIMEOUT_MS = 75_000;
/** Sin respuesta del servidor durante este tiempo, se asume que pudo dormirse. */
const STALE_AFTER_MS = 10 * 60_000;
/** Una espera más larga que esto (con el servidor posiblemente dormido) muestra el aviso. */
const SLOW_NOTICE_AFTER_MS = 4_000;
/** Pausa antes del único reintento de una lectura segura que falló por red o 503. */
const RETRY_DELAY_MS = 2_000;
const WARMUP_BUDGET_MS = 75_000;
const WARMUP_PAUSE_MS = 3_000;
const WARMUP_MAX_ATTEMPTS = 3;

/**
 * - `http`: el servidor respondió con un error.
 * - `network` / `timeout`: no hubo respuesta; el resultado de la operación es incierto.
 * - `invalid`: respondió con un cuerpo que no es el esperado.
 * - `not_sent`: la operación NO se envió (el servidor no despertó a tiempo): es seguro repetirla.
 */
export type ApiErrorKind = "http" | "network" | "timeout" | "invalid" | "not_sent";

/** Error de la API. `status` es 0 cuando no hubo respuesta (red o tiempo). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: ApiErrorKind,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/**
 * ¿Pudo la operación haberse ejecutado aunque no tengamos su respuesta? Es lo que ocurre
 * con un corte o un tiempo agotado (status 0) y con un 5xx. Un 4xx, o una operación que
 * nunca se envió (`not_sent`), son definitivos.
 */
export function isUncertainOutcome(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.kind !== "not_sent" &&
    (error.status === 0 || error.status >= 500)
  );
}

export interface ApiClient {
  /**
   * Despierta el servidor con GET /health si pudo dormirse (una sola vez por episodio,
   * con espera acotada). Nunca lanza. No es un mantenimiento periódico: solo se pide
   * cuando una persona abre una pantalla o va a crear una sesión.
   */
  warmUp(): Promise<boolean>;
  /**
   * `beforeSend` se invoca justo antes de enviar el POST (y solo si llega a enviarse: no se
   * invoca si el servidor no despertó). Sirve para dejar constancia de una operación que,
   * si se pierde su respuesta, quedaría con resultado incierto.
   */
  createSession(input: CreateSessionInput, hooks?: { beforeSend?: () => void }): Promise<Session>;
  getSession(id: string): Promise<Session>;
  nextQuestion(id: string): Promise<Question>;
  answer(id: string, input: AnswerInput): Promise<Attempt>;
  abandon(id: string): Promise<Session>;
  attempts(id: string): Promise<Attempt[]>;
  ranking(): Promise<RankingRow[]>;
  /** Figura de una pregunta ya emitida (con la sesión del usuario). */
  figure(id: string, position: number, name: string): Promise<Blob>;
}

type FetchLike = typeof fetch;
type Shape = Record<string, "string" | "number" | "boolean" | "array" | "string?" | "number?">;

/** Comprueba la forma mínima de una respuesta; protege de cambios del backend. */
function expectShape<T>(json: unknown, shape: Shape, what: string): T {
  if (typeof json !== "object" || json === null) {
    throw new ApiError(0, "invalid", `Respuesta inesperada (${what})`);
  }
  const record = json as Record<string, unknown>;
  for (const [key, type] of Object.entries(shape)) {
    const value = record[key];
    const optional = type.endsWith("?");
    const base = type.replace("?", "");
    const ok =
      (optional && value === null) ||
      (base === "array" ? Array.isArray(value) : typeof value === base);
    if (!ok) {
      throw new ApiError(0, "invalid", `Respuesta inesperada (${what}.${key})`);
    }
  }
  return json as T;
}

const SESSION_SHAPE: Shape = {
  id: "string", mode: "string", question_count: "number", status: "string",
  answered_count: "number", server_now: "string",
  current_position: "number?", current_deadline_at: "string?",
};
const QUESTION_SHAPE: Shape = {
  position: "number", area: "string", statement_md: "string", options: "array",
  assets: "array", deadline_at: "string", server_now: "string",
};
const ATTEMPT_SHAPE: Shape = {
  position: "number", is_correct: "boolean", timed_out: "boolean",
  time_used_ms: "number", correct_option: "string", selected_option: "string?",
  area: "string", source_number: "number",
};
const RANKING_SHAPE: Shape = {
  display_name: "string", questions_seen: "number", correct_count: "number",
  sessions_completed: "number", is_me: "boolean",
  rank_position: "number?", accuracy_pct: "number?", avg_time_seconds: "number?",
};

export interface ApiOptions {
  /** Reloj (ms); para pruebas. */
  now?: () => number;
  /** Pausa; para pruebas. */
  sleep?: (ms: number) => Promise<void>;
  /** Último momento en que el servidor respondió (ms); para pruebas. Sin él, se asume dormido. */
  lastAliveAt?: number;
  /**
   * Avisa una sola vez cuando una espera con el servidor posiblemente dormido se alarga
   * (`true`) y cuando termina (`false`). La pantalla decide cómo anunciarlo.
   */
  onWaiting?: (waiting: boolean) => void;
}

/**
 * Cuánto esperar por una petición:
 * - `normal`: 15 s siempre (respuestas, abandonar, crear sesión: el reloj de la pregunta
 *   no admite esperar de más).
 * - `patient`: 75 s solo si el servidor pudo dormirse; para lecturas y `/next`, que se
 *   pueden repetir sin efecto adicional.
 */
type Policy = "normal" | "patient";

export function createApiClient(
  baseUrl: string,
  getToken: () => Promise<string | null>,
  fetchImpl: FetchLike = (...args) => fetch(...args),
  options: ApiOptions = {},
): ApiClient {
  const root = baseUrl.replace(/\/+$/, "");
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  let lastAliveAt: number | null = options.lastAliveAt ?? null;
  let waiting = 0;
  let warming: Promise<boolean> | null = null;

  const isStale = (): boolean => lastAliveAt === null || now() - lastAliveAt > STALE_AFTER_MS;

  /** Programa el aviso de espera; devuelve la función que lo cancela o lo retira. */
  function armSlowNotice(): () => void {
    let shown = false;
    const handle = setTimeout(() => {
      shown = true;
      waiting += 1;
      if (waiting === 1) options.onWaiting?.(true);
    }, SLOW_NOTICE_AFTER_MS);
    return () => {
      clearTimeout(handle);
      if (shown) {
        waiting -= 1;
        if (waiting === 0) options.onWaiting?.(false);
      }
    };
  }

  /** Envía la petición con la sesión del usuario. Lanza `ApiError` si no hay respuesta. */
  async function send(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    policy: Policy = "normal",
  ): Promise<Response> {
    const token = await getToken();
    if (!token) {
      throw new ApiError(401, "http", "No hay sesión iniciada");
    }
    const maybeAsleep = isStale();
    const timeoutMs = maybeAsleep && policy === "patient" ? PATIENT_TIMEOUT_MS : REQUEST_TIMEOUT_MS;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const releaseNotice = maybeAsleep ? armSlowNotice() : () => {};
    let response: Response;
    try {
      response = await fetchImpl(`${root}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError(0, "timeout", "El servidor no respondió a tiempo");
      }
      throw new ApiError(0, "network", "No se pudo conectar con el servidor");
    } finally {
      clearTimeout(timer);
      releaseNotice();
    }
    // Cualquier respuesta por debajo de 500 prueba que el proceso está despierto.
    if (response.status < 500) lastAliveAt = now();
    return response;
  }

  async function request(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    policy: Policy = "normal",
  ): Promise<unknown> {
    const response = await send(method, path, body, policy);
    let json: unknown = null;
    try {
      json = await response.json();
    } catch {
      /* cuerpo vacío o no JSON */
    }
    if (!response.ok) {
      const detail =
        typeof json === "object" && json !== null && typeof (json as { detail?: unknown }).detail === "string"
          ? (json as { detail: string }).detail
          : `Error HTTP ${response.status}`;
      throw new ApiError(response.status, "http", detail);
    }
    return json;
  }

  const sid = (id: string) => encodeURIComponent(id);

  /** Un fallo de red o un 503 de una lectura segura se reintenta UNA vez, sin bucles. */
  async function safeRead<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      const transient =
        error instanceof ApiError &&
        ((error.status === 0 && error.kind === "network") ||
          (error.status === 503 && error.kind === "http"));
      if (!transient) throw error;
      await sleep(RETRY_DELAY_MS);
      return operation();
    }
  }

  async function pingHealth(timeoutMs: number): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(`${root}/health`, { signal: controller.signal });
      if (!response.ok) return false;
      const body: unknown = await response.json();
      return typeof body === "object" && body !== null && (body as { ok?: unknown }).ok === true;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function runWarmUp(): Promise<boolean> {
    const started = now();
    const releaseNotice = armSlowNotice();
    try {
      for (let attempt = 0; attempt < WARMUP_MAX_ATTEMPTS; attempt += 1) {
        const left = WARMUP_BUDGET_MS - (now() - started);
        if (left <= 0) break;
        if (await pingHealth(Math.min(left, PATIENT_TIMEOUT_MS))) {
          lastAliveAt = now();
          return true;
        }
        if (WARMUP_BUDGET_MS - (now() - started) <= WARMUP_PAUSE_MS) break;
        await sleep(WARMUP_PAUSE_MS);
      }
      return false;
    } finally {
      releaseNotice();
    }
  }

  function warmUp(): Promise<boolean> {
    if (!isStale()) return Promise.resolve(true);
    warming ??= runWarmUp().finally(() => {
      warming = null;
    });
    return warming;
  }

  return {
    warmUp,
    async createSession(input, hooks) {
      // El servidor se despierta ANTES de enviar: si no despierta, la operación no se envió
      // y es seguro repetirla; si se enviara a ciegas, un corte dejaría un resultado incierto.
      if (!(await warmUp())) {
        throw new ApiError(
          0,
          "not_sent",
          "El servidor no respondió a tiempo. No se envió nada: puedes intentarlo de nuevo.",
        );
      }
      hooks?.beforeSend?.();
      return expectShape<Session>(await request("POST", "/sessions", input), SESSION_SHAPE, "sesión");
    },
    async getSession(id) {
      return safeRead(async () =>
        expectShape<Session>(
          await request("GET", `/sessions/${sid(id)}`, undefined, "patient"),
          SESSION_SHAPE,
          "sesión",
        ),
      );
    },
    async nextQuestion(id) {
      // Idempotente en el servidor (repite la pregunta pendiente con su mismo plazo) y por
      // eso sin reintento automático: lo repite la persona, con el mismo resultado.
      return expectShape<Question>(
        await request("POST", `/sessions/${sid(id)}/next`, undefined, "patient"),
        QUESTION_SHAPE,
        "pregunta",
      );
    },
    async answer(id, input) {
      return expectShape<Attempt>(await request("POST", `/sessions/${sid(id)}/answer`, input), ATTEMPT_SHAPE, "intento");
    },
    async abandon(id) {
      return expectShape<Session>(await request("POST", `/sessions/${sid(id)}/abandon`), SESSION_SHAPE, "sesión");
    },
    async attempts(id) {
      return safeRead(async () => {
        const json = await request("GET", `/sessions/${sid(id)}/attempts`, undefined, "patient");
        if (!Array.isArray(json)) {
          throw new ApiError(0, "invalid", "Respuesta inesperada (intentos)");
        }
        return json.map((item) => expectShape<Attempt>(item, ATTEMPT_SHAPE, "intento"));
      });
    },
    async ranking() {
      return safeRead(async () => {
        const json = await request("GET", "/ranking", undefined, "patient");
        if (!Array.isArray(json)) {
          throw new ApiError(0, "invalid", "Respuesta inesperada (ranking)");
        }
        return json.map((item) => expectShape<RankingRow>(item, RANKING_SHAPE, "ranking"));
      });
    },
    async figure(id, position, name) {
      const path = `/sessions/${sid(id)}/questions/${position}/assets/${encodeURIComponent(name)}`;
      return safeRead(async () => {
        const response = await send("GET", path, undefined, "patient");
        if (!response.ok) {
          throw new ApiError(response.status, "http", `Error HTTP ${response.status}`);
        }
        const type = (response.headers.get("content-type") ?? "").split(";")[0]!.trim();
        if (!["image/png", "image/jpeg", "image/webp"].includes(type)) {
          throw new ApiError(0, "invalid", "La figura no es una imagen");
        }
        return response.blob();
      });
    },
  };
}

export type HealthResult = { ok: true } | { ok: false; message: string };

/**
 * Comprueba GET /health. No necesita sesión. Nunca lanza. Solo prueba que el proceso
 * responde: NO prueba la conexión con la base de datos.
 */
export async function checkHealth(
  baseUrl: string,
  fetchImpl: FetchLike = (...args) => fetch(...args),
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<HealthResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${baseUrl.replace(/\/+$/, "")}/health`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      return { ok: false, message: `El servidor respondió con HTTP ${response.status}.` };
    }
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && (body as { ok?: unknown }).ok === true) {
      return { ok: true };
    }
    return { ok: false, message: "La respuesta del servidor no tiene el formato esperado." };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return { ok: false, message: "El servidor no respondió a tiempo." };
    }
    return { ok: false, message: "No se pudo contactar al servidor. ¿Está en ejecución?" };
  } finally {
    clearTimeout(timer);
  }
}
