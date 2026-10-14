/**
 * Comportamiento de punta a punta (cliente real de API + controlador + un servidor simulado
 * que implementa la semántica real de las rutas) ante respuestas perdidas y esperas largas.
 *
 * El servidor simulado copia lo que hace el backend (`routes_game.py` / `postgres.py`):
 * - POST /sessions/{id}/next NO es una lectura: repite la pregunta pendiente con el MISMO
 *   plazo, pero si ya venció registra su timeout y EMITE la siguiente (o cierra la sesión).
 * - POST .../answer es idempotente: repetir la posición devuelve el intento guardado; si el
 *   plazo venció, el servidor lo registra como sin respuesta aunque se haya elegido opción.
 * El reloj del servidor es el mismo reloj simulado de la prueba.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiClient } from "./api";
import { PlayController, type PlayState } from "./play";
import { remainingMs } from "./timer";
import type { Attempt } from "./types";

const DEADLINE_MS = 90_000;
const SESSION_ID = "s1";

type Row = Omit<Attempt, "selected_option"> & { selected_option: string | null };

class FakeServer {
  issued: number[] = [];
  attempts: Row[] = [];
  pending: { position: number; deadlineMs: number } | null = null;
  private nextPosition = 1;
  readonly count = 4;

  private iso(ms: number): string {
    return new Date(ms).toISOString();
  }

  private question(): unknown {
    const p = this.pending!;
    return {
      position: p.position, area: "econometria", statement_md: `Pregunta ${p.position}`,
      options: [{ label: "A", text_md: "a" }, { label: "B", text_md: "b" }, { label: "C", text_md: "c" }],
      assets: [], deadline_at: this.iso(p.deadlineMs), server_now: this.iso(Date.now()),
    };
  }

  private expire(): void {
    if (this.pending && Date.now() >= this.pending.deadlineMs) {
      this.attempts.push(this.row(this.pending.position, null, true));
      this.pending = null;
    }
  }

  private row(position: number, selected: string | null, timedOut: boolean): Row {
    return {
      position, selected_option: selected, is_correct: !timedOut && selected === "A",
      timed_out: timedOut, time_used_ms: timedOut ? DEADLINE_MS : 5_000, correct_option: "A",
      area: "econometria", source_number: position,
    };
  }

  handle(method: string, path: string, body: unknown): { status: number; json: unknown } {
    if (path === "/health") return { status: 200, json: { ok: true } };
    if (path === `/sessions/${SESSION_ID}` && method === "GET") {
      const done = this.attempts.length >= this.count;
      return {
        status: 200,
        json: {
          id: SESSION_ID, mode: "random", area: null, stage: null, question_count: this.count,
          status: done ? "completed" : "active", answered_count: this.attempts.length,
          current_position: this.pending?.position ?? null,
          current_deadline_at: this.pending ? this.iso(this.pending.deadlineMs) : null,
          server_now: this.iso(Date.now()),
        },
      };
    }
    if (path === `/sessions/${SESSION_ID}/next` && method === "POST") {
      this.expire(); // venció sin respuesta: el servidor registra el timeout
      if (!this.pending) {
        if (this.attempts.length >= this.count) {
          return { status: 409, json: { detail: "No quedan preguntas pendientes" } };
        }
        this.pending = { position: this.nextPosition, deadlineMs: Date.now() + DEADLINE_MS };
        this.issued.push(this.nextPosition);
        this.nextPosition += 1;
      }
      return { status: 200, json: this.question() };
    }
    if (path === `/sessions/${SESSION_ID}/answer` && method === "POST") {
      const { position, selected_option } = body as { position: number; selected_option: string | null };
      const saved = this.attempts.find((a) => a.position === position);
      if (saved) return { status: 200, json: saved }; // idempotente
      if (!this.pending || this.pending.position !== position) {
        return { status: 409, json: { detail: "La pregunta no ha sido emitida" } };
      }
      const expired = Date.now() >= this.pending.deadlineMs;
      const row = this.row(position, expired ? null : selected_option, expired);
      this.attempts.push(row);
      this.pending = null;
      return { status: 200, json: row };
    }
    if (path === `/sessions/${SESSION_ID}/attempts` && method === "GET") {
      return { status: 200, json: this.attempts };
    }
    return { status: 404, json: { detail: "no existe" } };
  }
}

interface Plan {
  /** Espera antes de que el servidor ATIENDA la petición (p. ej. el servicio despertando). */
  serverDelayMs?: number;
  /** Tiempo que tarda en llegar la respuesta una vez atendida. */
  responseDelayMs?: number;
  /** El servidor la atiende, pero la respuesta nunca llega. */
  lost?: boolean;
  /** La conexión falla de inmediato (sin llegar al servidor). */
  networkError?: boolean;
  /** Responde con este estado sin atender la petición (p. ej. 503 de la base de datos). */
  status?: number;
}

interface Harness {
  server: FakeServer;
  controller: PlayController;
  states: PlayState[];
  /** Cada petición, en el momento en que el cliente la envía: "POST /sessions/s1/answer {...}". */
  calls: string[];
  plan: { current: (call: string) => Plan };
  last: () => PlayState;
  count: (prefix: string) => number;
}

function harness(opts: { awake?: boolean } = {}): Harness {
  const server = new FakeServer();
  const calls: string[] = [];
  const plan: Harness["plan"] = { current: () => ({}) };

  const fetchImpl = ((url: string, init?: RequestInit) =>
    new Promise<Response>((resolve, reject) => {
      const method = init?.method ?? "GET";
      const path = new URL(url).pathname;
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      const label = `${method} ${path}`;
      calls.push(body ? `${label} ${JSON.stringify(body)}` : label);
      const p = plan.current(label);
      const timers: ReturnType<typeof setTimeout>[] = [];
      init?.signal?.addEventListener("abort", () => {
        timers.forEach(clearTimeout);
        reject(new DOMException("Aborted", "AbortError"));
      });
      if (p.networkError) return reject(new TypeError("Failed to fetch"));
      if (p.status) {
        return resolve(
          new Response(JSON.stringify({ detail: "Base de datos no disponible" }), {
            status: p.status, headers: { "Content-Type": "application/json" },
          }),
        );
      }
      // Sin espera: se atiende en el acto (así `await` no depende del reloj simulado).
      const after = (ms: number, fn: () => void) => (ms > 0 ? void timers.push(setTimeout(fn, ms)) : fn());
      after(p.serverDelayMs ?? 0, () => {
        const r = server.handle(method, path, body);
        if (p.lost) return;
        after(p.responseDelayMs ?? 0, () =>
          resolve(
            new Response(JSON.stringify(r.json), {
              status: r.status, headers: { "Content-Type": "application/json" },
            }),
          ),
        );
      });
    })) as unknown as typeof fetch;

  const api = createApiClient("http://api.test", async () => "token-de-prueba", fetchImpl, {
    lastAliveAt: opts.awake === false ? undefined : Date.now(),
  });
  const states: PlayState[] = [];
  const controller = new PlayController(api, (s) => states.push(s), () => Date.now());
  return {
    server, controller, states, calls, plan,
    last: () => states.at(-1)!,
    count: (prefix) => calls.filter((c) => c.startsWith(prefix)).length,
  };
}

/** Avanza el reloj simulado y deja resolverse las promesas pendientes. */
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-12T12:00:00Z"));
});
afterEach(() => vi.useRealTimers());

function questionRemainingMs(state: PlayState): number {
  if (state.kind !== "question") throw new Error(`Se esperaba una pregunta y hay ${state.kind}`);
  return remainingMs(Date.parse(state.question.deadline_at), Date.now(), state.offsetMs);
}

// ---------------------------------------------------------------------------------------------

describe("POST /next no es una lectura: respuesta perdida al emitir una pregunta", () => {
  async function lostNext() {
    const h = harness();
    h.plan.current = (call) => (call === "POST /sessions/s1/next" ? { lost: true } : {});
    const t0 = Date.now();
    const opening = h.controller.open(SESSION_ID);
    await advance(15_000); // el servidor emitió la pregunta 1; la respuesta nunca llegó: tiempo agotado
    await opening;
    expect(h.last()).toMatchObject({ kind: "error", reason: "unavailable" });
    expect(h.server.issued).toEqual([1]); // la pregunta SÍ se emitió en el servidor
    return { h, t0 };
  }

  it("el cliente no repite /next solo: ni a los 15 s ni minutos después", async () => {
    const { h } = await lostNext();

    await advance(10 * 60_000);

    expect(h.count("POST /sessions/s1/next")).toBe(1);
    expect(h.server.issued).toEqual([1]);
  });

  it.each([
    ["un corte de red", { networkError: true }],
    ["un 503 de la base de datos", { status: 503 }],
  ])("%s en /next tampoco se repite solo (no es una lectura: puede avanzar la sesión)", async (_l, plan) => {
    const h = harness();
    h.plan.current = (call) => (call === "POST /sessions/s1/next" ? plan : {});

    const opening = h.controller.open(SESSION_ID);
    await advance(10 * 60_000);
    await opening;

    expect(h.last()).toMatchObject({ kind: "error", reason: "unavailable" });
    expect(h.count("POST /sessions/s1/next")).toBe(1);
    expect(h.server.issued).toEqual([]); // y la sesión no avanzó
  });

  it("al reintentar a mano ANTES del plazo recibe la misma pregunta con el mismo plazo", async () => {
    const { h, t0 } = await lostNext();
    await advance(20_000); // t0 + 35 s
    h.plan.current = () => ({});

    await h.controller.retry();

    expect(h.last()).toMatchObject({ kind: "question" });
    const q = (h.last() as Extract<PlayState, { kind: "question" }>).question;
    expect(q.position).toBe(1);
    expect(Date.parse(q.deadline_at)).toBe(t0 + DEADLINE_MS); // el del servidor, no uno nuevo
    expect(h.server.issued).toEqual([1]); // no se emitió otra pregunta
    expect(h.server.attempts).toEqual([]); // y no se registró ningún timeout
    // Lo consumido cuenta: quedan 55 s, no 90.
    expect(questionRemainingMs(h.last())).toBe(DEADLINE_MS - 35_000);
  });

  it("al reintentar justo en el límite del plazo (90 s) el servidor registra el timeout y avanza UNA posición", async () => {
    const { h, t0 } = await lostNext();
    await advance(t0 + DEADLINE_MS - Date.now()); // exactamente el instante del vencimiento
    h.plan.current = () => ({});

    await h.controller.retry();

    expect(h.server.attempts.map((a) => [a.position, a.timed_out])).toEqual([[1, true]]);
    expect(h.server.issued).toEqual([1, 2]);
    const q = (h.last() as Extract<PlayState, { kind: "question" }>).question;
    expect(q.position).toBe(2);
    expect(Date.parse(q.deadline_at)).toBe(Date.now() + DEADLINE_MS); // plazo nuevo del servidor
  });

  it("un segundo antes del límite todavía devuelve la misma pregunta", async () => {
    const { h, t0 } = await lostNext();
    await advance(t0 + DEADLINE_MS - 1_000 - Date.now());
    h.plan.current = () => ({});

    await h.controller.retry();

    expect((h.last() as Extract<PlayState, { kind: "question" }>).question.position).toBe(1);
    expect(h.server.attempts).toEqual([]);
    expect(questionRemainingMs(h.last())).toBe(1_000);
  });

  it("pasado el límite, un reintento tardío no se salta preguntas: una por vez", async () => {
    const { h } = await lostNext();
    await advance(10 * 60_000); // muchísimo después del plazo
    h.plan.current = () => ({});

    await h.controller.retry();

    // La 1 quedó como sin respuesta, la 2 se emite; la 3 y la 4 NO se tocan.
    expect(h.server.attempts.map((a) => a.position)).toEqual([1]);
    expect(h.server.issued).toEqual([1, 2]);
  });
});

describe("recuperar una pregunta cuyo plazo ya corre (recarga con el servidor dormido)", () => {
  async function sleepingServerWithRunningQuestion() {
    const h = harness({ awake: false }); // el cliente no sabe si el servidor está despierto
    h.server.handle("POST", "/sessions/s1/next", undefined); // la pregunta 1 se emitió en t = 0
    await advance(30_000); // pasan 30 s (recarga, reposo...)
    return h;
  }

  it("la petición va directa, sin /health delante: la latencia es la del servidor, no una espera añadida", async () => {
    const h = await sleepingServerWithRunningQuestion();
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 40_000 } : {});
    const started = Date.now();

    const opening = h.controller.open(SESSION_ID);
    await advance(0);
    expect(h.calls).toEqual(["GET /sessions/s1"]); // lo primero que se envía es la recuperación
    await advance(40_000);
    await opening;

    expect(h.calls.some((c) => c.includes("/health"))).toBe(false);
    expect(Date.now() - started).toBe(40_000); // exactamente lo que tardó el servidor en despertar
    expect(h.last()).toMatchObject({ kind: "question" });
  });

  it("el plazo sigue siendo el del servidor: lo consumido durante el despertar ya no está disponible", async () => {
    const h = await sleepingServerWithRunningQuestion();
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 40_000 } : {});

    const opening = h.controller.open(SESSION_ID);
    await advance(40_000);
    await opening;

    const q = (h.last() as Extract<PlayState, { kind: "question" }>).question;
    expect(Date.parse(q.deadline_at)).toBe(Date.parse("2026-10-12T12:00:00Z") + DEADLINE_MS);
    expect(questionRemainingMs(h.last())).toBe(DEADLINE_MS - 70_000); // 20 s, no 90 s
    expect(h.server.issued).toEqual([1]);
  });

  it("si el servidor despierta después de vencida la pregunta, la recuperación la da por vencida", async () => {
    const h = await sleepingServerWithRunningQuestion();
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 70_000 } : {});

    const opening = h.controller.open(SESSION_ID); // llega en t = 100 s: ya venció a los 90 s
    await advance(70_000);
    await opening;

    expect(h.server.attempts.map((a) => [a.position, a.timed_out])).toEqual([[1, true]]);
    expect((h.last() as Extract<PlayState, { kind: "question" }>).question.position).toBe(2);
  });
});

describe("espera de hasta 75 s: el límite y lo que pasa después", () => {
  it("una respuesta a los 74 s todavía sirve", async () => {
    const h = harness({ awake: false });
    h.server.handle("POST", "/sessions/s1/next", undefined);
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 74_000 } : {});

    const opening = h.controller.open(SESSION_ID);
    await advance(73_999);
    expect(h.last()).toMatchObject({ kind: "loading" }); // sigue esperando, sin abortar
    await advance(1);
    await opening;

    expect(h.last()).toMatchObject({ kind: "question" });
    expect(h.count("GET /sessions/s1")).toBe(1);
  });

  it("a los 75 s se acaba la espera: un único intento, sin bucle ni /health", async () => {
    const h = harness({ awake: false });
    h.server.handle("POST", "/sessions/s1/next", undefined);
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 80_000 } : {});

    const opening = h.controller.open(SESSION_ID);
    await advance(74_999);
    expect(h.last()).toMatchObject({ kind: "loading" });
    await advance(1); // 75 000 ms
    await opening;

    expect(h.last()).toMatchObject({ kind: "error", reason: "unavailable" });
    await advance(10 * 60_000); // después del límite: nada se repite solo
    expect(h.count("GET /sessions/s1")).toBe(1);
    expect(h.count("POST")).toBe(0); // y el servidor no avanzó por nuestra cuenta
    expect(h.calls.some((c) => c.includes("/health"))).toBe(false);
  });

  it("tras el límite, el reintento manual con el servidor ya despierto recupera la sesión", async () => {
    const h = harness({ awake: false });
    h.server.handle("POST", "/sessions/s1/next", undefined);
    h.plan.current = (call) => (call === "GET /sessions/s1" ? { serverDelayMs: 80_000 } : {});
    const opening = h.controller.open(SESSION_ID);
    await advance(75_000);
    await opening;
    await advance(20_000); // a los 95 s: la pregunta 1 (emitida en t = 0) ya venció
    h.plan.current = () => ({});

    await h.controller.retry();

    expect(h.last()).toMatchObject({ kind: "question" });
    expect(h.server.attempts.map((a) => a.timed_out)).toEqual([true]);
  });
});

describe("responder con la respuesta perdida", () => {
  async function onFirstQuestion() {
    const h = harness();
    await h.controller.open(SESSION_ID);
    expect(h.last()).toMatchObject({ kind: "question" });
    return h;
  }
  const answers = (h: Harness) => h.calls.filter((c) => c.startsWith("POST /sessions/s1/answer"));

  it("guardada pero sin respuesta: se muestra el intento guardado, sin reenviar ni pedir otra pregunta", async () => {
    const h = await onFirstQuestion();
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { lost: true } : {});

    const submitting = h.controller.submit("B");
    await advance(15_000); // límite de espera de un envío
    await submitting;

    expect(h.last()).toMatchObject({ kind: "result" });
    const attempt = (h.last() as Extract<PlayState, { kind: "result" }>).attempt;
    expect(attempt).toMatchObject({ position: 1, selected_option: "B", is_correct: false });
    expect(answers(h)).toHaveLength(1);
    expect(h.count("POST /sessions/s1/next")).toBe(1); // solo la emisión inicial
    expect(h.count("GET /sessions/s1/attempts")).toBe(1);
    await advance(5 * 60_000);
    expect(answers(h)).toHaveLength(1); // ningún reintento automático, ni después
  });

  it("que el envío no haya llegado: permite reenviar la MISMA posición y opción, sin otra pregunta", async () => {
    const h = await onFirstQuestion();
    // El servidor tardaría 30 s en atenderla: el cliente se rinde a los 15 s y nunca llega.
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { serverDelayMs: 30_000 } : {});
    const submitting = h.controller.submit("B");
    await advance(15_000);
    await submitting;
    await advance(30_000); // el servidor nunca la atiende (la conexión ya se cortó)
    expect(h.last()).toMatchObject({ kind: "unconfirmed", saved: "missing", option: "B" });
    expect(h.server.attempts).toEqual([]);
    h.plan.current = () => ({});

    await h.controller.resendAnswer();

    expect(h.last()).toMatchObject({ kind: "result" });
    expect(answers(h)).toEqual([
      'POST /sessions/s1/answer {"position":1,"selected_option":"B"}',
      'POST /sessions/s1/answer {"position":1,"selected_option":"B"}',
    ]);
    expect(h.count("POST /sessions/s1/next")).toBe(1); // no se pidió otra pregunta antes de resolver
    expect(h.server.attempts).toHaveLength(1);
  });

  it("reenviada DESPUÉS del plazo: el servidor decide (sin respuesta); misma posición, ninguna pregunta nueva", async () => {
    const h = await onFirstQuestion();
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { serverDelayMs: 30_000 } : {});
    const submitting = h.controller.submit("B");
    await advance(15_000);
    await submitting;
    await advance(95_000); // ya pasó el plazo de 90 s de la pregunta
    h.plan.current = () => ({});

    await h.controller.resendAnswer();

    const attempt = (h.last() as Extract<PlayState, { kind: "result" }>).attempt;
    expect(attempt).toMatchObject({ position: 1, timed_out: true, selected_option: null });
    expect(answers(h)[1]).toBe('POST /sessions/s1/answer {"position":1,"selected_option":"B"}'); // sin cambiar nada
    expect(h.count("POST /sessions/s1/next")).toBe(1);
    expect(h.server.attempts.map((a) => a.position)).toEqual([1]);
  });

  it("si tampoco se puede comprobar, no se reenvía: un GET fallido no es 'no se guardó'", async () => {
    const h = await onFirstQuestion();
    h.plan.current = (call) =>
      call.startsWith("POST /sessions/s1/answer") || call === "GET /sessions/s1/attempts"
        ? { lost: true }
        : {};

    const submitting = h.controller.submit("B");
    await advance(15_000); // se pierde el envío
    await advance(2_000 + 15_000); // y la comprobación (con su único reintento de lectura)
    await submitting;

    expect(h.last()).toMatchObject({ kind: "unconfirmed", saved: "unknown" });
    expect(answers(h)).toHaveLength(1);
    await h.controller.resendAnswer(); // no debe enviar nada
    expect(answers(h)).toHaveLength(1);
  });

  it("en el límite del tiempo de envío: a 14 s llega; pasados 15 s se abandona la espera", async () => {
    const h = await onFirstQuestion();
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { responseDelayMs: 14_000 } : {});
    const fast = h.controller.submit("A");
    await advance(14_000);
    await fast;
    expect(h.last()).toMatchObject({ kind: "result" });
    expect(h.count("GET /sessions/s1/attempts")).toBe(0); // llegó: no hizo falta resincronizar

    // La siguiente pregunta, con la respuesta del servidor tardando 16 s.
    await h.controller.continue();
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { responseDelayMs: 16_000 } : {});
    const slow = h.controller.submit("C");
    await advance(15_000); // se rinde en 15 s exactos; el servidor ya la había guardado
    await slow;

    expect(h.last()).toMatchObject({ kind: "result" });
    expect(h.count("GET /sessions/s1/attempts")).toBe(1);
    expect(answers(h)).toHaveLength(2); // una por pregunta: nada duplicado
  });

  it("nunca hay calentamiento delante de un envío ni de una recuperación con el servidor activo", async () => {
    const h = await onFirstQuestion();
    h.plan.current = (call) => (call.startsWith("POST /sessions/s1/answer") ? { lost: true } : {});
    const submitting = h.controller.submit("B");
    await advance(15_000);
    await submitting;
    await advance(10 * 60_000);

    expect(h.calls.some((c) => c.includes("/health"))).toBe(false);
  });
});
