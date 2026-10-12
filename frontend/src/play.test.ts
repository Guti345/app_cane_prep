import { describe, expect, it } from "vitest";
import { ApiError, type ApiClient } from "./api";
import { PlayController, describeFailure, type PlayState } from "./play";
import type { Attempt, Question, Session } from "./types";

const NOW = Date.parse("2026-10-12T12:00:00Z");

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: "s1", mode: "random", area: null, stage: null, question_count: 2,
    status: "active", answered_count: 0, current_position: null,
    current_deadline_at: null, server_now: "2026-10-12T12:00:00Z", ...overrides,
  };
}

function question(position: number, serverNow = "2026-10-12T12:00:00Z"): Question {
  return {
    position, area: "econometria", statement_md: `Pregunta ${position}`,
    options: [
      { label: "A", text_md: "a" }, { label: "B", text_md: "b" }, { label: "C", text_md: "c" },
    ],
    assets: [], deadline_at: "2026-10-12T12:01:30Z", server_now: serverNow,
  };
}

function attempt(position: number, overrides: Partial<Attempt> = {}): Attempt {
  return {
    position, selected_option: "A", is_correct: true, timed_out: false,
    time_used_ms: 4000, correct_option: "A", ...overrides,
  };
}

/** API falsa: cada método se reemplaza por prueba. */
function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  const unexpected = (name: string) => async () => {
    throw new Error(`Llamada inesperada: ${name}`);
  };
  return {
    createSession: unexpected("createSession"),
    getSession: async () => session(),
    nextQuestion: unexpected("nextQuestion"),
    answer: unexpected("answer"),
    abandon: unexpected("abandon"),
    attempts: async () => [],
    ranking: unexpected("ranking"),
    ...overrides,
  } as ApiClient;
}

function run(api: ApiClient) {
  const states: PlayState[] = [];
  const controller = new PlayController(api, (s) => states.push(s), () => NOW);
  return { controller, states, last: () => states.at(-1)! };
}

describe("abrir una sesión", () => {
  it("muestra la pregunta pendiente con el desfase de reloj", async () => {
    // El servidor dice 12:00:30 y el cliente cree que son las 12:00:00: +30 s.
    const api = fakeApi({ nextQuestion: async () => question(1, "2026-10-12T12:00:30Z") });
    const { controller, last } = run(api);

    await controller.open("s1");

    expect(last()).toMatchObject({ kind: "question", offsetMs: 30_000 });
    expect((last() as { question: Question }).question.position).toBe(1);
  });

  it("al recargar muestra la misma pregunta pendiente", async () => {
    const api = fakeApi({
      getSession: async () => session({ answered_count: 1, current_position: 2 }),
      nextQuestion: async () => question(2),
    });
    const { controller, last } = run(api);

    await controller.open("s1");

    expect((last() as { question: Question }).question.position).toBe(2);
  });

  it("una sesión ya cerrada va directo al resumen", async () => {
    const api = fakeApi({
      getSession: async () => session({ status: "completed", answered_count: 2 }),
      attempts: async () => [attempt(1), attempt(2)],
    });
    const { controller, last } = run(api);

    await controller.open("s1");

    expect(last()).toMatchObject({ kind: "summary" });
    expect((last() as { attempts: Attempt[] }).attempts).toHaveLength(2);
  });
});

describe("responder", () => {
  function playing(attemptResult: Attempt | Error) {
    return fakeApi({
      nextQuestion: async () => question(1),
      answer: async () => {
        if (attemptResult instanceof Error) throw attemptResult;
        return attemptResult;
      },
    });
  }

  it("pasa de pregunta a resultado", async () => {
    const { controller, states, last } = run(playing(attempt(1)));
    await controller.open("s1");

    await controller.submit("A");

    expect(states.map((s) => s.kind)).toEqual(["loading", "question", "submitting", "result"]);
    expect(last()).toMatchObject({ kind: "result", isLast: false });
  });

  it("marca la última pregunta para ofrecer el resumen", async () => {
    const api = fakeApi({
      getSession: async () => session({ question_count: 1 }),
      nextQuestion: async () => question(1),
      answer: async () => attempt(1),
    });
    const { controller, last } = run(api);
    await controller.open("s1");

    await controller.submit("A");

    expect(last()).toMatchObject({ kind: "result", isLast: true });
  });

  it("un vencimiento se envía como opción nula y resulta en timeout", async () => {
    let sent: unknown;
    const api = fakeApi({
      nextQuestion: async () => question(1),
      answer: async (_id, input) => {
        sent = input;
        return attempt(1, { selected_option: null, is_correct: false, timed_out: true, time_used_ms: 90000 });
      },
    });
    const { controller, last } = run(api);
    await controller.open("s1");

    await controller.submit(null);

    expect(sent).toEqual({ position: 1, selected_option: null });
    expect((last() as { attempt: Attempt }).attempt.timed_out).toBe(true);
  });

  it("ignora un segundo envío mientras el primero está en curso", async () => {
    let calls = 0;
    let release!: (a: Attempt) => void;
    const api = fakeApi({
      nextQuestion: async () => question(1),
      answer: () => {
        calls += 1;
        return new Promise<Attempt>((resolve) => { release = resolve; });
      },
    });
    const { controller } = run(api);
    await controller.open("s1");

    const first = controller.submit("A");
    await controller.submit("B");
    release(attempt(1));
    await first;

    expect(calls).toBe(1);
  });

  it("si el servidor responde 409, se resincroniza", async () => {
    let opened = 0;
    const api = fakeApi({
      getSession: async () => { opened += 1; return session(); },
      nextQuestion: async () => question(1),
      answer: async () => { throw new ApiError(409, "http", "no emitida"); },
    });
    const { controller } = run(api);
    await controller.open("s1");

    await controller.submit("A");

    expect(opened).toBe(2);
  });
});

describe("continuar y cerrar", () => {
  it("sin preguntas pendientes (409) muestra el resumen", async () => {
    let n = 0;
    const api = fakeApi({
      getSession: async () => session({ status: n > 1 ? "completed" : "active" }),
      nextQuestion: async () => {
        n += 1;
        if (n > 1) throw new ApiError(409, "http", "No quedan preguntas pendientes");
        return question(1);
      },
      answer: async () => attempt(1),
      attempts: async () => [attempt(1), attempt(2, { selected_option: null, is_correct: false, timed_out: true })],
    });
    const { controller, last } = run(api);
    await controller.open("s1");
    await controller.submit("A");

    await controller.continue();

    expect(last()).toMatchObject({ kind: "summary" });
    expect((last() as { attempts: Attempt[] }).attempts[1]!.timed_out).toBe(true);
  });

  it("abandonar lleva al resumen", async () => {
    const api = fakeApi({
      nextQuestion: async () => question(1),
      abandon: async () => session({ status: "abandoned" }),
      getSession: async () => session({ status: "abandoned" }),
      attempts: async () => [],
    });
    const { controller, last } = run(api);
    await controller.open("s1");

    await controller.abandon();

    expect(last()).toMatchObject({ kind: "summary" });
  });
});

describe("fallos", () => {
  it.each([
    [new ApiError(401, "http", ""), "auth"],
    [new ApiError(403, "http", ""), "forbidden"],
    [new ApiError(404, "http", ""), "notfound"],
    [new ApiError(503, "http", ""), "unavailable"],
    [new ApiError(0, "network", ""), "unavailable"],
    [new ApiError(422, "http", ""), "unexpected"],
    [new Error("otra cosa"), "unexpected"],
  ])("%s -> %s", (error, reason) => {
    expect(describeFailure(error).reason).toBe(reason);
  });

  it("un fallo de red al abrir ofrece reintentar y se recupera", async () => {
    let fail = true;
    const api = fakeApi({
      getSession: async () => {
        if (fail) throw new ApiError(0, "network", "sin red");
        return session();
      },
      nextQuestion: async () => question(1),
    });
    const { controller, states } = run(api);

    await controller.open("s1");
    expect(states.at(-1)).toMatchObject({ kind: "error", reason: "unavailable" });

    fail = false;
    await controller.retry();

    expect(states.at(-1)).toMatchObject({ kind: "question" });
  });
});
