import type {
  AnswerInput,
  Attempt,
  CreateSessionInput,
  Question,
  RankingRow,
  Session,
} from "./types";

const REQUEST_TIMEOUT_MS = 15_000;

export type ApiErrorKind = "http" | "network" | "timeout" | "invalid";

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

export interface ApiClient {
  createSession(input: CreateSessionInput): Promise<Session>;
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
};
const RANKING_SHAPE: Shape = {
  display_name: "string", questions_seen: "number", correct_count: "number",
  sessions_completed: "number", is_me: "boolean",
  rank_position: "number?", accuracy_pct: "number?", avg_time_seconds: "number?",
};

export function createApiClient(
  baseUrl: string,
  getToken: () => Promise<string | null>,
  fetchImpl: FetchLike = (...args) => fetch(...args),
): ApiClient {
  const root = baseUrl.replace(/\/+$/, "");

  /** Envía la petición con la sesión del usuario. Lanza `ApiError` si no hay respuesta. */
  async function send(method: "GET" | "POST", path: string, body?: unknown): Promise<Response> {
    const token = await getToken();
    if (!token) {
      throw new ApiError(401, "http", "No hay sesión iniciada");
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
    }
    return response;
  }

  async function request(method: "GET" | "POST", path: string, body?: unknown): Promise<unknown> {
    const response = await send(method, path, body);
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

  return {
    async createSession(input) {
      return expectShape<Session>(await request("POST", "/sessions", input), SESSION_SHAPE, "sesión");
    },
    async getSession(id) {
      return expectShape<Session>(await request("GET", `/sessions/${sid(id)}`), SESSION_SHAPE, "sesión");
    },
    async nextQuestion(id) {
      return expectShape<Question>(await request("POST", `/sessions/${sid(id)}/next`), QUESTION_SHAPE, "pregunta");
    },
    async answer(id, input) {
      return expectShape<Attempt>(await request("POST", `/sessions/${sid(id)}/answer`, input), ATTEMPT_SHAPE, "intento");
    },
    async abandon(id) {
      return expectShape<Session>(await request("POST", `/sessions/${sid(id)}/abandon`), SESSION_SHAPE, "sesión");
    },
    async attempts(id) {
      const json = await request("GET", `/sessions/${sid(id)}/attempts`);
      if (!Array.isArray(json)) {
        throw new ApiError(0, "invalid", "Respuesta inesperada (intentos)");
      }
      return json.map((item) => expectShape<Attempt>(item, ATTEMPT_SHAPE, "intento"));
    },
    async ranking() {
      const json = await request("GET", "/ranking");
      if (!Array.isArray(json)) {
        throw new ApiError(0, "invalid", "Respuesta inesperada (ranking)");
      }
      return json.map((item) => expectShape<RankingRow>(item, RANKING_SHAPE, "ranking"));
    },
    async figure(id, position, name) {
      const path = `/sessions/${sid(id)}/questions/${position}/assets/${encodeURIComponent(name)}`;
      const response = await send("GET", path);
      if (!response.ok) {
        throw new ApiError(response.status, "http", `Error HTTP ${response.status}`);
      }
      const type = (response.headers.get("content-type") ?? "").split(";")[0]!.trim();
      if (!["image/png", "image/jpeg", "image/webp"].includes(type)) {
        throw new ApiError(0, "invalid", "La figura no es una imagen");
      }
      return response.blob();
    },
  };
}

export type HealthResult = { ok: true } | { ok: false; message: string };

/** Comprueba GET /health. No necesita sesión. Nunca lanza. */
export async function checkHealth(
  baseUrl: string,
  fetchImpl: FetchLike = (...args) => fetch(...args),
): Promise<HealthResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
