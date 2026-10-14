// @vitest-environment jsdom
// Pantallas y avisos del arranque en frío: espera accesible, resultado incierto y
// la garantía de que responder una pregunta activa nunca pasa por el calentamiento.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api";
import type { Deps } from "../deps";
import { createPendingCreateStore } from "../pendingCreate";
import { createServerNotice, WAKING_MESSAGE } from "../serverNotice";
import type { Attempt, Question, Session } from "../types";
import { renderHome } from "./home";
import { renderPlayScreen } from "./playScreen";

const NOW = Date.parse("2026-10-12T12:00:00Z");
const SESSION_ID = "6d3b5ff7-c6f8-4bb6-966b-caa2ad7e1197";

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: SESSION_ID, mode: "random", area: null, stage: null, question_count: 2,
    status: "active", answered_count: 0, current_position: 1,
    current_deadline_at: null, server_now: "2026-10-12T12:00:00Z", ...overrides,
  };
}

const QUESTION: Question = {
  position: 1, area: "macroeconomia", statement_md: "¿Qué es el PIB?",
  options: [
    { label: "A", text_md: "Uno" }, { label: "B", text_md: "Dos" }, { label: "C", text_md: "Tres" },
  ],
  assets: [], deadline_at: "2026-10-12T12:01:30Z", server_now: "2026-10-12T12:00:00Z",
};

const ATTEMPT: Attempt = {
  position: 1, selected_option: "B", is_correct: false, timed_out: false, time_used_ms: 5000,
  correct_option: "A", area: "macroeconomia", source_number: 12,
};

function deps(api: Partial<ApiClient>): Deps & { went: unknown[] } {
  const went: unknown[] = [];
  return {
    auth: {
      signIn: async () => ({ ok: true }), signOut: async () => {},
      getAccessToken: async () => "t", getUserId: async () => "user-a", onSignedOut: () => () => {},
    },
    api: { warmUp: async () => true, ...api } as ApiClient,
    store: { get: () => null, set: () => {}, clear: () => {} },
    pendingCreate: createPendingCreateStore(null),
    apiUrl: "http://localhost:8000",
    go: (route) => void went.push(route),
    signOut: async () => {},
    went,
  };
}

let container: HTMLElement;
beforeEach(() => {
  container = document.createElement("div");
  document.body.replaceChildren(container);
});

// --- aviso accesible ------------------------------------------------------------------------

describe("aviso de espera del servidor", () => {
  it("es una región viva que ya existe vacía y no ocupa lugar hasta que hay texto", () => {
    const notice = createServerNotice(container);

    expect(notice.element.getAttribute("role")).toBe("status");
    expect(notice.element.getAttribute("aria-live")).toBe("polite");
    expect(notice.element.textContent).toBe("");
    expect(container.previousElementSibling).toBe(notice.element);
  });

  it("escribe el texto una vez, sin contador, y lo borra al terminar", () => {
    const notice = createServerNotice(container);
    const writes: string[] = [];
    new MutationObserver(() => writes.push(notice.element.textContent ?? "")).observe(notice.element, {
      childList: true, characterData: true, subtree: true,
    });

    notice.onWaiting(true);
    notice.onWaiting(true); // otra espera dentro del mismo episodio: sin cambiar nada

    expect(notice.element.textContent).toBe(WAKING_MESSAGE);
    expect(WAKING_MESSAGE).not.toMatch(/\d+\s*s\b/); // sin segundos contados
    notice.onWaiting(false);
    expect(notice.element.textContent).toBe("");
  });
});

// --- inicio: calentamiento y creación incierta -------------------------------------------------

describe("inicio", () => {
  function submitForm(): void {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  }
  const startButton = () => container.querySelector("button[type=submit]") as HTMLButtonElement;

  it("pide el calentamiento al abrirse y NO espera por él", async () => {
    const warmUp = vi.fn(() => new Promise<boolean>(() => {})); // nunca termina
    const d = deps({ warmUp });

    await renderHome(container, d); // debe resolver aunque el calentamiento siga pendiente

    expect(warmUp).toHaveBeenCalledTimes(1);
    expect(container.querySelector("form")).not.toBeNull();
  });

  it("si la creación queda incierta, avisa y bloquea repetirla", async () => {
    const createSession = vi.fn(async () => {
      throw new ApiError(0, "timeout", "El servidor no respondió a tiempo");
    });
    await renderHome(container, deps({ createSession }));

    submitForm();
    await vi.waitFor(() => expect(container.querySelector("[role=alert]")).not.toBeNull());

    const text = container.querySelector("[role=alert]")!.textContent!;
    expect(text).toContain("quedó sin confirmar");
    expect(text).toContain("bloqueado");
    expect(startButton().disabled).toBe(true);
    submitForm(); // por teclado (Enter) aunque el botón esté deshabilitado
    await Promise.resolve();
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("un 503 al crear también se considera incierto", async () => {
    const createSession = vi.fn(async () => {
      throw new ApiError(503, "http", "Base de datos no disponible");
    });
    await renderHome(container, deps({ createSession }));

    submitForm();
    await vi.waitFor(() => expect(startButton().disabled).toBe(true));
    submitForm();
    await Promise.resolve();

    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("si la operación no llegó a enviarse (servidor sin despertar) se puede repetir", async () => {
    const createSession = vi.fn(async () => {
      throw new ApiError(0, "not_sent", "El servidor no respondió a tiempo.");
    });
    await renderHome(container, deps({ createSession }));

    submitForm();
    await vi.waitFor(() => expect(container.querySelector("[role=alert]")).not.toBeNull());

    expect(startButton().disabled).toBe(false);
    submitForm();
    await vi.waitFor(() => expect(createSession).toHaveBeenCalledTimes(2));
  });

  it("un error definitivo (409, sin preguntas suficientes) deja reintentar", async () => {
    const createSession = vi.fn(async () => {
      throw new ApiError(409, "http", "No hay suficientes preguntas disponibles");
    });
    await renderHome(container, deps({ createSession }));

    submitForm();
    await vi.waitFor(() =>
      expect(container.querySelector("[role=alert]")?.textContent).toContain("No hay suficientes"),
    );

    expect(startButton().disabled).toBe(false);
  });

  it("una creación correcta lleva a la sesión", async () => {
    const d = deps({ createSession: async () => session() });
    await renderHome(container, d);

    submitForm();

    await vi.waitFor(() => expect(d.went).toEqual([{ name: "play", sessionId: SESSION_ID }]));
  });
});

// --- jugar: una respuesta perdida -------------------------------------------------------------------

describe("pantalla de juego con una respuesta perdida", () => {
  function playing(answer: ApiClient["answer"], attempts: ApiClient["attempts"]) {
    const nextQuestion = vi.fn(async () => QUESTION);
    const warmUp = vi.fn(async () => true);
    const d = deps({ getSession: async () => session(), nextQuestion, answer, attempts, warmUp });
    const stop = renderPlayScreen(container, d, SESSION_ID, () => NOW);
    return { d, nextQuestion, warmUp, stop };
  }
  const options = () => [...container.querySelectorAll<HTMLButtonElement>("button.option")];
  const labelled = (text: string) =>
    [...container.querySelectorAll("button")].find((b) => b.textContent?.includes(text)) as HTMLButtonElement;

  it("muestra que no quedó registrada y permite reenviar la misma respuesta", async () => {
    let saved = false;
    const answer = vi.fn(async () => {
      if (!saved) throw new ApiError(0, "network", "sin red");
      return ATTEMPT;
    });
    const { stop, nextQuestion, warmUp } = playing(answer, async () => []);
    await vi.waitFor(() => expect(options()).toHaveLength(3));

    options()[1]!.click(); // B
    await vi.waitFor(() => expect(container.textContent).toContain("no quedó registrada"));

    expect(labelled("Reenviar mi respuesta")).toBeDefined();
    expect(container.textContent).toContain("(B)"); // dice qué opción se reenviará
    saved = true;
    labelled("Reenviar mi respuesta").click();
    await vi.waitFor(() => expect(container.querySelector(".banner")).not.toBeNull());

    expect(answer).toHaveBeenCalledTimes(2);
    expect(answer.mock.calls.map((c) => (c as unknown[])[1])).toEqual([
      { position: 1, selected_option: "B" },
      { position: 1, selected_option: "B" },
    ]);
    expect(nextQuestion).toHaveBeenCalledTimes(1); // mismo plazo: ninguna pregunta nueva
    expect(warmUp).not.toHaveBeenCalled(); // jugar nunca pasa por el calentamiento
    stop();
  });

  it("si no se pudo comprobar, no ofrece reenviar y permite comprobar de nuevo", async () => {
    let works = false;
    const answer = vi.fn(async () => {
      throw new ApiError(0, "timeout", "no respondió");
    });
    const attempts = vi.fn(async () => {
      if (!works) throw new ApiError(0, "network", "sin red");
      return [ATTEMPT];
    });
    const { stop } = playing(answer, attempts);
    await vi.waitFor(() => expect(options()).toHaveLength(3));

    options()[1]!.click();
    await vi.waitFor(() => expect(container.textContent).toContain("No pudimos confirmar"));

    expect(container.textContent).not.toContain("Reenviar mi respuesta");
    works = true;
    labelled("Comprobar de nuevo").click();
    await vi.waitFor(() => expect(container.querySelector(".banner")).not.toBeNull());
    expect(answer).toHaveBeenCalledTimes(1);
    stop();
  });
});

// --- el reloj de la respuesta no espera al calentamiento -------------------------------------------

describe("garantías estructurales", () => {
  const sources = import.meta.glob<string>("/src/**/*.ts", {
    query: "?raw", import: "default", eager: true,
  });
  const read = (file: string): string => {
    const source = sources[`/src/${file}`];
    if (source === undefined) throw new Error(`No se encontró ${file}`);
    return source;
  };

  it("ni el controlador de juego ni la pantalla de pregunta usan el calentamiento", () => {
    for (const file of ["play.ts", "screens/question.ts", "screens/playScreen.ts", "screens/result.ts"]) {
      expect(read(file), file).not.toMatch(/warmUp/);
    }
  });

  it("solo el inicio, el arranque y crear sesión piden el calentamiento", () => {
    const users = ["main.ts", "screens/home.ts", "screens/ranking.ts", "screens/login.ts", "api.ts"].filter(
      (f) => /warmUp\(/.test(read(f)),
    );

    expect(users.sort()).toEqual(["api.ts", "main.ts", "screens/home.ts"]);
  });

  it("no hay temporizadores periódicos hacia /health (sin mantener despierto el servicio)", () => {
    expect(read("api.ts")).not.toMatch(/setInterval/);
    expect(read("main.ts")).not.toMatch(/setInterval/);
    expect(read("serverNotice.ts")).not.toMatch(/setInterval/);
  });
});
