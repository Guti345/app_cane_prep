import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, checkHealth, createApiClient, isUncertainOutcome } from "./api";
import attemptFixture from "./__fixtures__/attempt.json";
import attemptsFixture from "./__fixtures__/attempts.json";
import questionFixture from "./__fixtures__/question.json";
import rankingFixture from "./__fixtures__/ranking.json";
import sessionFixture from "./__fixtures__/session.json";

// Los fixtures son respuestas reales del backend (PostgreSQL local), no inventadas.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientWith(fetchImpl: typeof fetch, token: string | null = "token-de-prueba") {
  // El servidor "ya estaba despierto": estas pruebas no ejercitan el calentamiento.
  return createApiClient("http://localhost:8000/", async () => token, fetchImpl, { lastAliveAt: Date.now() });
}

describe("contrato con respuestas reales del backend", () => {
  it("acepta una sesión, una pregunta, un intento, la lista de intentos y el ranking", async () => {
    const responses: unknown[] = [
      sessionFixture, questionFixture, attemptFixture, attemptsFixture, rankingFixture,
    ];
    const api = clientWith(vi.fn(async () => jsonResponse(responses.shift())) as unknown as typeof fetch);

    const session = await api.createSession({ mode: "random", question_count: 2 });
    const question = await api.nextQuestion(session.id);
    const attempt = await api.answer(session.id, { position: 1, selected_option: "B" });
    const attempts = await api.attempts(session.id);
    const ranking = await api.ranking();

    expect(session.status).toBe("active");
    expect(question.position).toBe(1);
    expect(question.options.length).toBeGreaterThanOrEqual(3);
    expect(typeof question.server_now).toBe("string");
    expect(attempt.correct_option).toBe("A");
    expect(attempts.map((a) => a.position)).toEqual([1, 2]);
    expect(ranking[0]?.is_me).toBe(true);
  });

  it("la pregunta emitida no trae la respuesta correcta", () => {
    expect(JSON.stringify(questionFixture)).not.toContain("correct_option");
  });

  it("los fixtures conservan los acentos (sin doble codificación)", () => {
    const all = JSON.stringify([
      sessionFixture, questionFixture, attemptFixture, attemptsFixture, rankingFixture,
    ]);

    expect(all).not.toMatch(/[ÃÂ]/);
    expect(questionFixture.options[0]!.text_md).toBe("Opción A");
  });

  it("decodifica UTF-8 aunque la respuesta no declare charset", async () => {
    // Igual que el backend: application/json sin charset, cuerpo en UTF-8.
    const bytes = new TextEncoder().encode(JSON.stringify(questionFixture));
    const api = clientWith(
      (async () =>
        new Response(bytes, { headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch,
    );

    const question = await api.nextQuestion("x");

    expect(question.options[0]!.text_md).toBe("Opción A");
    expect(question.statement_md).toContain("¿Cuál");
  });

  it("el plazo de la pregunta es server_now + 90 s", () => {
    const remaining = Date.parse(questionFixture.deadline_at) - Date.parse(questionFixture.server_now);

    expect(remaining).toBeGreaterThan(85_000);
    expect(remaining).toBeLessThanOrEqual(90_000);
  });
});

describe("peticiones", () => {
  it("envía el token y el cuerpo JSON, sin credenciales en la URL", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(sessionFixture));
    const api = clientWith(fetchMock as unknown as typeof fetch);

    await api.createSession({ mode: "area", area: "econometria", question_count: 3 });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/sessions");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-de-prueba");
    expect(JSON.parse(init.body as string)).toEqual({
      mode: "area", area: "econometria", question_count: 3,
    });
    expect(url).not.toContain("token");
  });

  it("sin sesión no llama al servidor y devuelve 401", async () => {
    const fetchMock = vi.fn();
    const api = clientWith(fetchMock as unknown as typeof fetch, null);

    await expect(api.getSession("x")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("errores", () => {
  it("traduce un error HTTP con su detalle", async () => {
    const api = clientWith(
      (async () => jsonResponse({ detail: "La sesión ya no está activa" }, 409)) as unknown as typeof fetch,
    );

    const error = await api.nextQuestion("x").catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, kind: "http", detail: "La sesión ya no está activa" });
  });

  it("traduce un fallo de red", async () => {
    const api = clientWith((async () => { throw new TypeError("fallo"); }) as unknown as typeof fetch);

    await expect(api.ranking()).rejects.toMatchObject({ status: 0, kind: "network" });
  });

  it("rechaza respuestas con otra forma", async () => {
    const api = clientWith((async () => jsonResponse({ id: 1 })) as unknown as typeof fetch);

    await expect(api.getSession("x")).rejects.toMatchObject({ kind: "invalid" });
  });

  it("rechaza un ranking que no es una lista", async () => {
    const api = clientWith((async () => jsonResponse({})) as unknown as typeof fetch);

    await expect(api.ranking()).rejects.toMatchObject({ kind: "invalid" });
  });
});

describe("checkHealth", () => {
  it("ok con {ok: true}", async () => {
    const result = await checkHealth("http://x", (async () => jsonResponse({ ok: true })) as unknown as typeof fetch);

    expect(result).toEqual({ ok: true });
  });

  it("avisa si el servidor no responde", async () => {
    const result = await checkHealth("http://x", (async () => { throw new TypeError("x"); }) as unknown as typeof fetch);

    expect(result.ok).toBe(false);
  });

  it("avisa si responde con error HTTP", async () => {
    const result = await checkHealth("http://x", (async () => jsonResponse({}, 500)) as unknown as typeof fetch);

    expect(result).toMatchObject({ ok: false });
  });
});

describe("figure", () => {
  const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

  it("pide la figura de la posición con el token del usuario y devuelve el blob", async () => {
    const fetchImpl = vi.fn(
      async () => new Response(PNG, { status: 200, headers: { "Content-Type": "image/png" } }),
    );
    const api = clientWith(fetchImpl as unknown as typeof fetch);

    const blob = await api.figure("sesion 1", 2, "cane-2026-econometria-006-fig-01.png");

    expect(blob.type).toBe("image/png");
    expect(blob.size).toBe(4);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/sessions/sesion%201/questions/2/assets/cane-2026-econometria-006-fig-01.png");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-de-prueba");
  });

  it("una figura inexistente (404) es un error HTTP", async () => {
    const api = clientWith((async () => jsonResponse({ detail: "Figura no encontrada" }, 404)) as unknown as typeof fetch);

    await expect(api.figure("s", 1, "x.png")).rejects.toMatchObject({ status: 404, kind: "http" });
  });

  it("rechaza una respuesta que no es una imagen", async () => {
    const html = new Response("<script>alert(1)</script>", { status: 200, headers: { "Content-Type": "text/html" } });
    const api = clientWith((async () => html) as unknown as typeof fetch);

    await expect(api.figure("s", 1, "x.png")).rejects.toMatchObject({ kind: "invalid" });
  });

  it("sin sesión iniciada no hace ninguna petición", async () => {
    const fetchImpl = vi.fn();
    const api = clientWith(fetchImpl as unknown as typeof fetch, null);

    await expect(api.figure("s", 1, "x.png")).rejects.toBeInstanceOf(ApiError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

// --- arranque en frío del servidor (plan gratuito de Render) ----------------------------------

describe("arranque en frío", () => {
  interface Call { url: string; method: string }

  /** fetch falso: cada petición tarda `delayMs` (con el reloj simulado) y respeta el abort. */
  function slowFetch(
    delay: number | ((call: Call) => number),
    respond: (call: Call) => Response,
    calls: Call[],
  ) {
    return vi.fn((url: string, init?: RequestInit) => {
      const call = { url, method: init?.method ?? "GET" };
      calls.push(call);
      return new Promise<Response>((resolve, reject) => {
        const delayMs = typeof delay === "number" ? delay : delay(call);
        const timer = setTimeout(() => resolve(respond(call)), delayMs);
        init?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    });
  }

  const health = () => jsonResponse({ ok: true });
  const path = (call: Call) => new URL(call.url).pathname;

  function clientFor(
    fetchImpl: unknown,
    options: Parameters<typeof createApiClient>[3] = {},
    token: string | null = "token-de-prueba",
  ) {
    return createApiClient("http://localhost:8000/", async () => token, fetchImpl as typeof fetch, options);
  }

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  describe("calentamiento (GET /health)", () => {
    it("espera una respuesta de 40 s sin abortarla a los 15 s", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(40_000, health, calls));

      const result = api.warmUp();
      let settled: boolean | undefined;
      void result.then((v) => { settled = v; });
      await vi.advanceTimersByTimeAsync(16_000);

      expect(settled).toBeUndefined(); // sigue esperando: no se abortó a los 15 s
      await vi.advanceTimersByTimeAsync(25_000);
      expect(await result).toBe(true);
      expect(calls.map(path)).toEqual(["/health"]); // una sola petición, sin duplicados
    });

    it("tolera ~1 minuto de despertar y lo da por bueno", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(60_000, health, calls));

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(61_000);

      expect(await result).toBe(true);
      expect(calls).toHaveLength(1);
    });

    it("avisa UNA sola vez cuando la espera se alarga y lo retira al terminar", async () => {
      const onWaiting = vi.fn();
      const api = clientFor(slowFetch(60_000, health, []), { onWaiting });

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(3_000);
      expect(onWaiting).not.toHaveBeenCalled(); // aún no es "lento"
      await vi.advanceTimersByTimeAsync(2_000);
      expect(onWaiting.mock.calls).toEqual([[true]]);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(onWaiting.mock.calls).toEqual([[true]]); // sin repetir mientras dura
      await vi.advanceTimersByTimeAsync(30_000);
      await result;

      expect(onWaiting.mock.calls).toEqual([[true], [false]]);
    });

    it("no avisa si el servidor responde enseguida", async () => {
      const onWaiting = vi.fn();
      const api = clientFor(slowFetch(500, health, []), { onWaiting });

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(1_000);
      await result;

      expect(onWaiting).not.toHaveBeenCalled();
    });

    it("dos esperas lentas simultáneas se anuncian una sola vez", async () => {
      const onWaiting = vi.fn();
      const api = clientFor(slowFetch(30_000, (c) => (path(c) === "/health" ? health() : jsonResponse(sessionFixture)), []), { onWaiting });

      const warm = api.warmUp();
      const session = api.getSession("s1");
      await vi.advanceTimersByTimeAsync(31_000);
      await Promise.all([warm, session]);

      expect(onWaiting.mock.calls).toEqual([[true], [false]]);
    });

    it("no hace nada si el servidor respondió hace menos de 10 minutos", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(10, health, calls), { lastAliveAt: Date.now() - 9 * 60_000 });

      expect(await api.warmUp()).toBe(true);
      expect(calls).toHaveLength(0);
    });

    it("vuelve a calentar pasados 10 minutos sin respuesta", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(10, health, calls), { lastAliveAt: Date.now() - 11 * 60_000 });

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(100);

      expect(await result).toBe(true);
      expect(calls).toHaveLength(1);
    });

    it("una segunda llamada mientras calienta reutiliza la misma petición", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(20_000, health, calls));

      const a = api.warmUp();
      const b = api.warmUp();
      await vi.advanceTimersByTimeAsync(21_000);

      expect(await a).toBe(true);
      expect(await b).toBe(true);
      expect(calls).toHaveLength(1);
    });

    it("con la red caída hace un número acotado de intentos y no lanza", async () => {
      const calls: Call[] = [];
      const fetchImpl = vi.fn(async (url: string) => {
        calls.push({ url, method: "GET" });
        throw new TypeError("sin red");
      });
      const api = clientFor(fetchImpl);

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(120_000);

      expect(await result).toBe(false);
      expect(calls.length).toBeLessThanOrEqual(3);
      expect(calls.length).toBeGreaterThanOrEqual(2);
    });

    it("un 503 y luego un 200 terminan bien (un reintento del propio calentamiento)", async () => {
      const responses = [new Response("", { status: 503 }), jsonResponse({ ok: true })];
      const fetchImpl = vi.fn(async () => responses.shift()!);
      const api = clientFor(fetchImpl);

      const result = api.warmUp();
      await vi.advanceTimersByTimeAsync(10_000);

      expect(await result).toBe(true);
      expect(fetchImpl).toHaveBeenCalledTimes(2);
    });

    it("el calentamiento no envía el token (no es una petición autenticada)", async () => {
      const calls: RequestInit[] = [];
      const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
        calls.push(init ?? {});
        return health();
      });
      const api = clientFor(fetchImpl);

      await api.warmUp();

      expect(calls[0]?.headers).toBeUndefined();
    });
  });

  describe("crear sesión (POST no idempotente)", () => {
    it("espera el calentamiento y envía UN solo POST", async () => {
      const calls: Call[] = [];
      const api = clientFor(
        slowFetch(
          (c) => (path(c) === "/health" ? 40_000 : 500), // despierta en 40 s; el POST es rápido
          (c) => (path(c) === "/health" ? health() : jsonResponse(sessionFixture, 201)),
          calls,
        ),
      );

      const created = api.createSession({ mode: "random", question_count: 2 });
      await vi.advanceTimersByTimeAsync(41_000);
      await created;

      expect(calls.map((c) => `${c.method} ${path(c)}`)).toEqual(["GET /health", "POST /sessions"]);
    });

    it("avisa justo antes de enviar el POST, y después del calentamiento", async () => {
      const events: string[] = [];
      const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
        events.push(`${init?.method ?? "GET"} ${path({ url, method: "" })}`);
        return path({ url, method: "" }) === "/health" ? health() : jsonResponse(sessionFixture, 201);
      });
      const api = clientFor(fetchImpl);

      await api.createSession({ mode: "random", question_count: 2 }, {
        beforeSend: () => events.push("beforeSend"),
      });

      expect(events).toEqual(["GET /health", "beforeSend", "POST /sessions"]);
    });

    it("no avisa si el POST nunca llegó a enviarse (el servidor no despertó)", async () => {
      const beforeSend = vi.fn();
      const fetchImpl = vi.fn(async () => {
        throw new TypeError("sin red");
      });
      const api = clientFor(fetchImpl);

      const outcome = api.createSession({ mode: "random", question_count: 2 }, { beforeSend }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(120_000);

      expect(await outcome).toMatchObject({ kind: "not_sent" });
      expect(beforeSend).not.toHaveBeenCalled();
    });

    it("si el servidor no despierta NO envía el POST y el error es definitivo (not_sent)", async () => {
      const calls: Call[] = [];
      const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method ?? "GET" });
        throw new TypeError("sin red");
      });
      const api = clientFor(fetchImpl);

      const outcome = api.createSession({ mode: "random", question_count: 2 }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(120_000);
      const error = await outcome;

      expect(error).toMatchObject({ status: 0, kind: "not_sent" });
      expect(isUncertainOutcome(error)).toBe(false);
      expect(calls.some((c) => c.method === "POST")).toBe(false);
    });

    it("si la respuesta del POST se pierde, el resultado es incierto y no se reintenta", async () => {
      const calls: Call[] = [];
      const api = clientFor(
        slowFetch(60_000, (c) => (path(c) === "/health" ? health() : jsonResponse(sessionFixture)), calls),
        { lastAliveAt: Date.now() }, // el servidor ya estaba despierto
      );

      const outcome = api.createSession({ mode: "random", question_count: 2 }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(200_000);
      const error = await outcome;

      expect(error).toMatchObject({ kind: "timeout" });
      expect(isUncertainOutcome(error)).toBe(true);
      expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    });
  });

  describe("responder (la pregunta tiene plazo)", () => {
    it("se envía de inmediato, sin calentamiento previo, aunque el servidor esté 'dormido'", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(2_000, () => jsonResponse(attemptFixture), calls)); // sin lastAliveAt

      const sent = api.answer("s1", { position: 1, selected_option: "A" });
      await vi.advanceTimersByTimeAsync(0); // solo el microtask del token; ningún tiempo de espera

      expect(calls.map((c) => `${c.method} ${path(c)}`)).toEqual(["POST /sessions/s1/answer"]);
      await vi.advanceTimersByTimeAsync(2_500);
      await sent;
      expect(calls).toHaveLength(1);
    });

    it("usa el tiempo de espera normal (15 s), nunca el largo, y no se reintenta sola", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(60_000, () => jsonResponse(attemptFixture), calls));

      const outcome = api.answer("s1", { position: 1, selected_option: "A" }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(16_000);
      const error = await outcome;
      await vi.advanceTimersByTimeAsync(120_000); // por si hubiera un reintento tardío

      expect(error).toMatchObject({ status: 0, kind: "timeout" });
      expect(isUncertainOutcome(error)).toBe(true);
      expect(calls).toHaveLength(1);
    });

    it("con la red caída hace un único intento", async () => {
      const fetchImpl = vi.fn(async () => {
        throw new TypeError("sin red");
      });
      const api = clientFor(fetchImpl);

      const error = await api.answer("s1", { position: 1, selected_option: "A" }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(120_000);

      expect(error).toMatchObject({ kind: "network" });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    it("un 503 tampoco se reenvía solo", async () => {
      const fetchImpl = vi.fn(async () => jsonResponse({ detail: "Base de datos no disponible" }, 503));
      const api = clientFor(fetchImpl);

      const error = await api.answer("s1", { position: 1, selected_option: "A" }).catch((e) => e);
      await vi.advanceTimersByTimeAsync(60_000);

      expect(error).toMatchObject({ status: 503 });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });
  });

  describe("recuperar una pregunta cuyo plazo ya corre", () => {
    it("POST /next se envía de inmediato (sin /health delante) y espera hasta 75 s", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(50_000, () => jsonResponse(questionFixture), calls));

      const pending = api.nextQuestion("s1");
      await vi.advanceTimersByTimeAsync(0);
      expect(calls.map((c) => `${c.method} ${path(c)}`)).toEqual(["POST /sessions/s1/next"]);
      await vi.advanceTimersByTimeAsync(51_000);
      const question = await pending;

      expect(calls).toHaveLength(1);
      // El plazo es el del servidor: el cliente no lo reinicia ni lo amplía.
      expect(question.deadline_at).toBe(questionFixture.deadline_at);
      expect(question.server_now).toBe(questionFixture.server_now);
    });

    it("con el servidor despierto, /next conserva el tiempo de espera normal", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(30_000, () => jsonResponse(questionFixture), calls), {
        lastAliveAt: Date.now(),
      });

      const error = api.nextQuestion("s1").catch((e) => e);
      await vi.advanceTimersByTimeAsync(16_000);

      expect(await error).toMatchObject({ kind: "timeout" });
    });

    it("POST /next no se reintenta solo cuando falla", async () => {
      const fetchImpl = vi.fn(async () => {
        throw new TypeError("sin red");
      });
      const api = clientFor(fetchImpl);

      await api.nextQuestion("s1").catch(() => undefined);
      await vi.advanceTimersByTimeAsync(60_000);

      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });
  });

  describe("lecturas seguras (GET)", () => {
    it("un fallo de red se reintenta una vez y se recupera", async () => {
      const responses: Array<Response | Error> = [new TypeError("sin red"), jsonResponse([...rankingFixture])];
      const fetchImpl = vi.fn(async () => {
        const next = responses.shift()!;
        if (next instanceof Error) throw next;
        return next;
      });
      const api = clientFor(fetchImpl, { lastAliveAt: Date.now() });

      const ranking = api.ranking();
      await vi.advanceTimersByTimeAsync(3_000);

      expect((await ranking)[0]?.is_me).toBe(true);
      expect(fetchImpl).toHaveBeenCalledTimes(2);
    });

    it("un 503 se reintenta una vez; si vuelve a fallar, se acaba (sin bucle)", async () => {
      const fetchImpl = vi.fn(async () => jsonResponse({ detail: "Base de datos no disponible" }, 503));
      const api = clientFor(fetchImpl, { lastAliveAt: Date.now() });

      const outcome = api.attempts("s1").catch((e) => e);
      await vi.advanceTimersByTimeAsync(60_000);

      expect(await outcome).toMatchObject({ status: 503 });
      expect(fetchImpl).toHaveBeenCalledTimes(2);
    });

    it("no reintenta un error definitivo (404) ni un tiempo agotado", async () => {
      const notFound = vi.fn(async () => jsonResponse({ detail: "Sesión no encontrada" }, 404));
      await clientFor(notFound, { lastAliveAt: Date.now() }).getSession("x").catch(() => undefined);
      expect(notFound).toHaveBeenCalledTimes(1);

      const calls: Call[] = [];
      const slow = slowFetch(60_000, () => jsonResponse(sessionFixture), calls);
      const api = clientFor(slow, { lastAliveAt: Date.now() });
      const outcome = api.getSession("x").catch((e) => e);
      await vi.advanceTimersByTimeAsync(120_000);

      expect(await outcome).toMatchObject({ kind: "timeout" });
      expect(calls).toHaveLength(1);
    });

    it("con el servidor posiblemente dormido, una lectura espera hasta 75 s", async () => {
      const calls: Call[] = [];
      const api = clientFor(slowFetch(60_000, () => jsonResponse(sessionFixture), calls));

      const session = api.getSession("s1");
      await vi.advanceTimersByTimeAsync(61_000);

      expect((await session).id).toBe(sessionFixture.id);
      expect(calls).toHaveLength(1);
    });
  });

  it("isUncertainOutcome distingue lo definitivo de lo incierto", () => {
    expect(isUncertainOutcome(new ApiError(0, "network", ""))).toBe(true);
    expect(isUncertainOutcome(new ApiError(0, "timeout", ""))).toBe(true);
    expect(isUncertainOutcome(new ApiError(0, "invalid", ""))).toBe(true);
    expect(isUncertainOutcome(new ApiError(503, "http", ""))).toBe(true);
    expect(isUncertainOutcome(new ApiError(500, "http", ""))).toBe(true);
    expect(isUncertainOutcome(new ApiError(0, "not_sent", ""))).toBe(false);
    for (const status of [400, 401, 403, 404, 409, 422]) {
      expect(isUncertainOutcome(new ApiError(status, "http", ""))).toBe(false);
    }
    expect(isUncertainOutcome(new Error("otra cosa"))).toBe(false);
  });

  it("checkHealth admite una espera larga cuando se le pide", async () => {
    const calls: Call[] = [];
    const patient = checkHealth("http://x", slowFetch(40_000, health, calls) as unknown as typeof fetch, 75_000);
    await vi.advanceTimersByTimeAsync(41_000);
    expect(await patient).toEqual({ ok: true });

    const impatient = checkHealth("http://x", slowFetch(40_000, health, []) as unknown as typeof fetch);
    await vi.advanceTimersByTimeAsync(16_000);
    expect(await impatient).toMatchObject({ ok: false, message: "El servidor no respondió a tiempo." });
  });
});
