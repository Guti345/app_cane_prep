import { describe, expect, it, vi } from "vitest";
import { ApiError, checkHealth, createApiClient } from "./api";
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
  return createApiClient("http://localhost:8000/", async () => token, fetchImpl);
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
