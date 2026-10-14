// @vitest-environment jsdom
// Creación de sesión con resultado incierto: el bloqueo sobrevive a recargar, está ligado al
// usuario, no guarda tokens y solo lo libera una persona, pasado el tiempo de espera.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ApiClient } from "../api";
import type { Deps } from "../deps";
import { createPendingCreateStore, UNCERTAIN_HOLD_MS } from "../pendingCreate";
import type { Session } from "../types";
import { renderHome } from "./home";

const SESSION: Session = {
  id: "6d3b5ff7-c6f8-4bb6-966b-caa2ad7e1197", mode: "random", area: null, stage: null,
  question_count: 5, status: "active", answered_count: 0, current_position: null,
  current_deadline_at: null, server_now: "2026-10-12T12:00:00Z",
};

/** Almacenamiento del navegador simulado: lo comparten las "recargas" de una prueba. */
function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

interface World {
  storage: ReturnType<typeof memoryStorage>;
  clock: { t: number };
  /** Cuántas sesiones llegó a crear "el servidor". */
  created: { n: number };
  signedOut: string[];
}

function newWorld(): World {
  return { storage: memoryStorage(), clock: { t: Date.parse("2026-10-12T12:00:00Z") }, created: { n: 0 }, signedOut: [] };
}

/** Una "carga de la página": store nuevo (memoria vacía) sobre el mismo almacenamiento. */
function load(world: World, api: Partial<ApiClient>, userId: string | null = "user-a", activeId: string | null = null) {
  const went: unknown[] = [];
  const deps: Deps = {
    auth: {
      signIn: async () => ({ ok: true }), signOut: async () => {},
      getAccessToken: async () => "token-secreto-no-guardar",
      getUserId: async () => userId,
      onSignedOut: () => () => {},
    },
    api: { warmUp: async () => true, ...api } as ApiClient,
    store: { get: () => activeId, set: () => {}, clear: () => {} },
    pendingCreate: createPendingCreateStore(world.storage, () => world.clock.t),
    apiUrl: "http://localhost:8000",
    go: (route) => void went.push(route),
    signOut: async (notice) => void world.signedOut.push(notice ?? ""),
  };
  const container = document.createElement("div");
  document.body.replaceChildren(container);
  return { container, deps, went };
}

const form = (c: HTMLElement) => c.querySelector("form")!;
const submit = (c: HTMLElement) => form(c).dispatchEvent(new Event("submit", { cancelable: true }));
const startButton = (c: HTMLElement) => c.querySelector("button[type=submit]") as HTMLButtonElement;
const alertText = (c: HTMLElement) => c.querySelector("[role=alert]")?.textContent ?? "";
const acknowledge = (c: HTMLElement) =>
  [...c.querySelectorAll("button")].find((b) => b.textContent?.includes("Entiendo")) as HTMLButtonElement | undefined;
const settle = () => new Promise((r) => setTimeout(r, 0));

/** Un servidor que SÍ crea la sesión pero cuya respuesta nunca llega. */
function lostResponseApi(world: World): Partial<ApiClient> {
  return {
    createSession: vi.fn(async (_input, hooks) => {
      hooks?.beforeSend?.();
      world.created.n += 1; // el servidor la creó...
      throw new ApiError(0, "timeout", "El servidor no respondió a tiempo"); // ...y la respuesta se perdió
    }),
  };
}

let world: World;
beforeEach(() => {
  world = newWorld();
});

describe("respuesta perdida de POST /sessions, recarga y regreso al inicio", () => {
  it("tras recargar sigue bloqueado y NO se vuelve a crear a ciegas", async () => {
    const api = lostResponseApi(world);
    const first = load(world, api);
    await renderHome(first.container, first.deps);
    submit(first.container);
    await vi.waitFor(() => expect(alertText(first.container)).toContain("quedó sin confirmar"));
    expect(world.created.n).toBe(1);

    // Recarga: página nueva, mismo navegador (mismo almacenamiento), mismo usuario.
    const reloaded = load(world, api);
    await renderHome(reloaded.container, reloaded.deps);

    expect(startButton(reloaded.container).disabled).toBe(true);
    expect(alertText(reloaded.container)).toContain("quedó sin confirmar");
    expect(alertText(reloaded.container)).toContain("no lo resuelve"); // recargar no es una solución
    submit(reloaded.container); // Enter con el botón deshabilitado
    await settle();
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(world.created.n).toBe(1);
  });

  it("una recarga con la petición todavía en vuelo también deja el bloqueo", async () => {
    const inFlight = {
      createSession: vi.fn((_input: unknown, hooks?: { beforeSend?: () => void }) => {
        hooks?.beforeSend?.();
        return new Promise<Session>(() => {}); // nunca responde: la página se recarga antes
      }),
    } as Partial<ApiClient>;
    const first = load(world, inFlight);
    await renderHome(first.container, first.deps);
    submit(first.container);
    await vi.waitFor(() => expect(inFlight.createSession).toHaveBeenCalled());

    const reloaded = load(world, inFlight);
    await renderHome(reloaded.container, reloaded.deps);

    expect(startButton(reloaded.container).disabled).toBe(true);
    expect(alertText(reloaded.container)).toContain("quedó sin confirmar");
  });

  it("al volver a iniciar sesión con la misma cuenta sigue bloqueado; con otra cuenta no", async () => {
    const api = lostResponseApi(world);
    const a = load(world, api, "user-a");
    await renderHome(a.container, a.deps);
    submit(a.container);
    await vi.waitFor(() => expect(startButton(a.container).disabled).toBe(true));
    await vi.waitFor(() => expect(alertText(a.container)).toContain("quedó sin confirmar"));

    const sameUserAgain = load(world, api, "user-a");
    await renderHome(sameUserAgain.container, sameUserAgain.deps);
    expect(startButton(sameUserAgain.container).disabled).toBe(true);

    const otherUser = load(world, api, "user-b");
    await renderHome(otherUser.container, otherUser.deps);
    expect(startButton(otherUser.container).disabled).toBe(false); // no hereda el bloqueo
    expect(alertText(otherUser.container)).toBe("");
  });

  it("el bloqueo de un usuario no se aplica sin identidad conocida", async () => {
    const api = lostResponseApi(world);
    const a = load(world, api, "user-a");
    await renderHome(a.container, a.deps);
    submit(a.container);
    await vi.waitFor(() => expect(startButton(a.container).disabled).toBe(true));
    await vi.waitFor(() => expect(alertText(a.container)).toContain("quedó sin confirmar"));

    const noOne = load(world, api, null);
    await renderHome(noOne.container, noOne.deps);
    submit(noOne.container);
    await vi.waitFor(() => expect(world.signedOut).toHaveLength(1)); // pide iniciar sesión; no crea
    expect(api.createSession).toHaveBeenCalledTimes(1);
  });
});

describe("qué borra y qué no borra el bloqueo", () => {
  async function blocked() {
    const api = lostResponseApi(world);
    const page = load(world, api);
    await renderHome(page.container, page.deps);
    submit(page.container);
    await vi.waitFor(() => expect(alertText(page.container)).toContain("quedó sin confirmar"));
    return api;
  }

  it("encontrar una sesión activa (GET) no lo libera: no prueba que sea la de la petición perdida", async () => {
    const api = await blocked();
    const getSession = vi.fn(async () => SESSION);

    const page = load(world, { ...api, getSession }, "user-a", SESSION.id);
    await renderHome(page.container, page.deps);

    expect(getSession).toHaveBeenCalled(); // se ofrece "Continuar" como siempre
    expect(page.container.textContent).toContain("Tienes una sesión en curso");
    expect(startButton(page.container).disabled).toBe(true);
    expect(alertText(page.container)).toContain("quedó sin confirmar");
    expect([...world.storage.data.keys()].some((k) => k.endsWith("user-a"))).toBe(true);
  });

  it("un GET vacío o fallido tampoco lo libera", async () => {
    const api = await blocked();
    for (const getSession of [
      vi.fn(async () => { throw new ApiError(404, "http", "Sesión no encontrada"); }),
      vi.fn(async () => { throw new ApiError(0, "network", "sin red"); }),
    ]) {
      const page = load(world, { ...api, getSession }, "user-a", "otra-sesion");
      await renderHome(page.container, page.deps);
      expect(startButton(page.container).disabled).toBe(true);
    }
  });

  it("no se libera con el simple paso del tiempo: hace falta reconocerlo, y solo después de la espera", async () => {
    const api = await blocked();

    const early = load(world, api);
    world.clock.t += UNCERTAIN_HOLD_MS - 60_000;
    await renderHome(early.container, early.deps);
    expect(acknowledge(early.container)).toBeUndefined(); // aún pudo completarse
    expect(startButton(early.container).disabled).toBe(true);

    const late = load(world, api);
    world.clock.t += 120_000;
    await renderHome(late.container, late.deps);
    expect(startButton(late.container).disabled).toBe(true); // pasó el tiempo, sigue bloqueado
    expect(acknowledge(late.container)).toBeDefined();
    expect(alertText(late.container)).toContain("no podemos comprobar");
  });

  it("reconocerlo (a mano) habilita crear otra sesión y se crea UNA", async () => {
    const lost = await blocked();
    const ok = { createSession: vi.fn(async () => SESSION) } as Partial<ApiClient>;
    world.clock.t += UNCERTAIN_HOLD_MS + 1_000;
    const page = load(world, { ...lost, ...ok });
    await renderHome(page.container, page.deps);

    acknowledge(page.container)!.click();
    await vi.waitFor(() => expect(startButton(page.container).disabled).toBe(false));
    submit(page.container);

    await vi.waitFor(() => expect(page.went).toEqual([{ name: "play", sessionId: SESSION.id }]));
    expect(ok.createSession).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["una sesión creada", async () => SESSION],
    ["un 409 del servidor", async () => { throw new ApiError(409, "http", "No hay suficientes preguntas disponibles"); }],
    ["un 422 del servidor", async () => { throw new ApiError(422, "http", "inválido"); }],
    ["una operación no enviada", async () => { throw new ApiError(0, "not_sent", "No despertó"); }],
  ])("%s es un resultado definitivo: no deja bloqueo", async (_label, behaviour) => {
    const createSession = vi.fn(async (_i: unknown, hooks?: { beforeSend?: () => void }) => {
      hooks?.beforeSend?.();
      return behaviour();
    });
    const page = load(world, { createSession } as Partial<ApiClient>);
    await renderHome(page.container, page.deps);
    submit(page.container);
    await vi.waitFor(() => expect(createSession).toHaveBeenCalled());
    await settle();

    expect([...world.storage.data.keys()]).toEqual([]);
    const reloaded = load(world, { createSession } as Partial<ApiClient>);
    await renderHome(reloaded.container, reloaded.deps);
    expect(startButton(reloaded.container).disabled).toBe(false);
  });

  it("un 5xx (503) se trata como incierto", async () => {
    const createSession = vi.fn(async (_i: unknown, hooks?: { beforeSend?: () => void }) => {
      hooks?.beforeSend?.();
      throw new ApiError(503, "http", "Base de datos no disponible");
    });
    const page = load(world, { createSession } as Partial<ApiClient>);
    await renderHome(page.container, page.deps);
    submit(page.container);

    await vi.waitFor(() => expect(alertText(page.container)).toContain("quedó sin confirmar"));
    expect(world.storage.data.size).toBe(1);
  });
});

describe("qué se guarda", () => {
  it("solo el momento, bajo una clave del usuario; ni token ni datos de la sesión", async () => {
    const page = load(world, lostResponseApi(world));
    await renderHome(page.container, page.deps);
    submit(page.container);
    await vi.waitFor(() => expect(world.storage.data.size).toBe(1));

    const [[key, value]] = [...world.storage.data.entries()];
    expect(key).toBe("cane.pendingCreate.v1.user-a");
    expect(Object.keys(JSON.parse(value!))).toEqual(["at"]);
    const everything = JSON.stringify([...world.storage.data.entries()]);
    expect(everything).not.toContain("token");
    expect(everything).not.toContain("secreto");
  });

  it("si el almacenamiento falla, el bloqueo vale al menos mientras la página siga abierta", async () => {
    const broken = {
      getItem: () => { throw new Error("bloqueado"); },
      setItem: () => { throw new Error("bloqueado"); },
      removeItem: () => { throw new Error("bloqueado"); },
    };
    const store = createPendingCreateStore(broken, () => world.clock.t);

    store.set("user-a");

    expect(store.get("user-a")).toEqual({ at: world.clock.t });
    expect(store.get("user-b")).toBeNull();
    store.clear("user-a");
    expect(store.get("user-a")).toBeNull();
  });

  it("ignora un valor guardado con otra forma", () => {
    const storage = memoryStorage({
      "cane.pendingCreate.v1.user-a": "no-es-json",
      "cane.pendingCreate.v1.user-b": JSON.stringify({ at: "ayer" }),
    });
    const store = createPendingCreateStore(storage, () => 0);

    expect(store.get("user-a")).toBeNull();
    expect(store.get("user-b")).toBeNull();
  });
});
