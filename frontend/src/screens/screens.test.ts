// @vitest-environment jsdom
// jsdom: estas pantallas pasan por DOMPurify, que no es fiable con happy-dom.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api";
import type { Deps } from "../deps";
import { createPendingCreateStore } from "../pendingCreate";
import type { AuthService, SignInResult } from "../supabase";
import type { Attempt, Question, RankingRow, Session } from "../types";
import { navBar } from "./layout";
import { renderLogin } from "./login";
import { renderQuestion } from "./question";
import { positionLabel, renderRankingTable } from "./ranking";
import { renderResult } from "./result";
import { renderSummary, summarize } from "./summary";

function deps(signIn: (e: string, p: string) => Promise<SignInResult>): Deps & { went: unknown[] } {
  const went: unknown[] = [];
  const auth: AuthService = {
    signIn,
    signOut: async () => {},
    getAccessToken: async () => null,
    getUserId: async () => null,
    onSignedOut: () => () => {},
  };
  return {
    auth,
    api: {} as ApiClient,
    store: { get: () => null, set: () => {}, clear: () => {} },
    pendingCreate: createPendingCreateStore(null),
    apiUrl: "http://localhost:8000",
    go: (route) => void went.push(route),
    signOut: async () => {},
    went,
  };
}

const SESSION: Session = {
  id: "s1", mode: "random", area: null, stage: null, question_count: 3,
  status: "active", answered_count: 0, current_position: 1,
  current_deadline_at: null, server_now: "2026-10-12T12:00:00Z",
};

const BASE_NOW = Date.parse("2026-10-12T12:00:00Z");

function question(overrides: Partial<Question> = {}): Question {
  return {
    position: 1, area: "macroeconomia", statement_md: "¿Qué es el PIB?",
    options: [
      { label: "A", text_md: "Uno" }, { label: "B", text_md: "Dos" }, { label: "C", text_md: "Tres" },
    ],
    assets: [], deadline_at: "2026-10-12T12:01:30Z", server_now: "2026-10-12T12:00:00Z",
    ...overrides,
  };
}

function click(el: Element | null): void {
  (el as HTMLElement).click();
}

// --- login ---------------------------------------------------------------------

describe("pantalla de login", () => {
  let container: HTMLElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.replaceChildren(container);
  });

  function fill(email: string, password: string) {
    (container.querySelector("#email") as HTMLInputElement).value = email;
    (container.querySelector("#password") as HTMLInputElement).value = password;
    container.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  }

  it("no ofrece registro y explica quién cambia la contraseña", () => {
    renderLogin(container, deps(async () => ({ ok: true })));

    expect(container.textContent).toContain("administrador");
    expect(container.textContent?.toLowerCase()).not.toContain("registrar");
    expect((container.querySelector("#password") as HTMLInputElement).type).toBe("password");
  });

  it("pide los dos campos antes de llamar a Auth", async () => {
    const signIn = vi.fn(async () => ({ ok: true }) as SignInResult);
    renderLogin(container, deps(signIn));

    fill("", "");
    await Promise.resolve();

    expect(signIn).not.toHaveBeenCalled();
    expect(container.querySelector("[role=alert]")?.textContent).toContain("Escribe tu correo");
  });

  it("con credenciales válidas va al inicio y borra la contraseña", async () => {
    const d = deps(async () => ({ ok: true }));
    renderLogin(container, d);

    fill("persona@ejemplo.test", "secreta");
    await vi.waitFor(() => expect(d.went).toEqual([{ name: "home" }]));

    expect((container.querySelector("#password") as HTMLInputElement).value).toBe("");
  });

  it("con credenciales inválidas muestra el error y permite reintentar", async () => {
    const d = deps(async () => ({ ok: false, message: "Correo o contraseña incorrectos." }));
    renderLogin(container, d);

    fill("persona@ejemplo.test", "mala");
    await vi.waitFor(() =>
      expect(container.querySelector("[role=alert]")?.textContent).toBe("Correo o contraseña incorrectos."),
    );

    expect(d.went).toEqual([]);
    expect((container.querySelector("button[type=submit]") as HTMLButtonElement).disabled).toBe(false);
  });
});

// --- pregunta con cronómetro ---------------------------------------------------------

describe("pantalla de pregunta", () => {
  let container: HTMLElement;
  let now: number;

  beforeEach(() => {
    vi.useFakeTimers();
    now = BASE_NOW;
    container = document.createElement("div");
    document.body.replaceChildren(container);
  });
  afterEach(() => vi.useRealTimers());

  function show(q: Question, offsetMs = 0, loadFigure?: (ref: string) => Promise<string>) {
    const onAnswer = vi.fn();
    const onAbandon = vi.fn();
    const stop = renderQuestion(container, {
      session: SESSION, question: q, offsetMs, onAnswer, onAbandon, loadFigure, now: () => now,
    });
    const advance = (ms: number) => {
      now += ms;
      vi.advanceTimersByTime(ms);
    };
    return { onAnswer, onAbandon, stop, advance };
  }

  it("muestra el enunciado, las opciones y 1:30", () => {
    show(question());

    expect(container.querySelector(".statement")?.textContent).toBe("¿Qué es el PIB?");
    expect([...container.querySelectorAll(".option")].map((b) => b.getAttribute("data-label"))).toEqual(["A", "B", "C"]);
    expect(container.querySelector(".timer")?.textContent).toBe("1:30");
    expect(container.textContent).toContain("Pregunta 1 de 3");
  });

  it("dibuja ecuaciones y tablas del enunciado y ecuaciones en las opciones", () => {
    show(question({
      statement_md: "Sea $x^2$ el cuadrado.\n\n| a | b |\n|---|---|\n| 1 | 2 |",
      options: [
        { label: "A", text_md: "$a_i + b_j$" }, { label: "B", text_md: "**dos**" }, { label: "C", text_md: "tres" },
      ],
    }));

    expect(container.querySelector(".statement .katex")).not.toBeNull();
    expect(container.querySelector(".statement table td")?.textContent).toBe("1");
    expect(container.querySelector('.option[data-label="A"] .katex')).not.toBeNull();
    expect(container.querySelector('.option[data-label="B"] strong')?.textContent).toBe("dos");
  });

  it("carga la figura listada con el cargador autenticado y descarta la ajena", async () => {
    const ref = "assets/cane-2026-econometria-006-fig-01.png";
    const loadFigure = vi.fn().mockResolvedValue("blob:http://localhost/figura");
    show(
      question({
        statement_md: `Observe la serie:\n\n![serie](${ref})\n\n![ajena](https://evil.test/p.png)`,
        assets: [{ ref, kind: "figure", alt: "Serie", source_page: 3, status: "available" }],
      }),
      0,
      loadFigure,
    );

    const images = container.querySelectorAll("img");
    expect(images).toHaveLength(1);
    await vi.waitFor(() => expect(images[0]!.getAttribute("src")).toBe("blob:http://localhost/figura"));
    expect(loadFigure).toHaveBeenCalledTimes(1);
    expect(loadFigure).toHaveBeenCalledWith(ref);
    expect(container.innerHTML).not.toContain("evil.test");
  });

  it("si la figura no carga, la pregunta sigue siendo respondible", async () => {
    const ref = "assets/cane-2026-econometria-006-fig-01.png";
    const { onAnswer } = show(
      question({
        statement_md: `![serie](${ref})`,
        assets: [{ ref, kind: "figure", alt: "Serie", source_page: 3, status: "available" }],
      }),
      0,
      () => Promise.reject(new Error("404")),
    );

    await vi.waitFor(() => expect(container.querySelector(".figure-missing")).not.toBeNull());
    click(container.querySelector('.option[data-label="B"]'));

    expect(onAnswer).toHaveBeenCalledWith("B");
  });

  it("una ecuación inválida no rompe la pantalla ni el cronómetro", () => {
    const { advance, onAnswer } = show(question({ statement_md: "Antes $x^{2$ después." }));

    expect(container.querySelector(".statement .katex-error")).not.toBeNull();
    expect(container.querySelector(".statement")?.textContent).toContain("después.");
    advance(1000);
    expect(container.querySelector(".timer")?.textContent).toBe("1:29");
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("el HTML del enunciado y de las opciones se muestra como texto, no se ejecuta", () => {
    show(question({
      statement_md: '<img src=x onerror="alert(1)"><script>alert(2)</script>',
      options: [
        { label: "A", text_md: "<b>negrita</b>" },
        { label: "B", text_md: "<a href='javascript:alert(3)'>x</a>" },
        { label: "C", text_md: "normal" },
      ],
    }));

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector(".option b")).toBeNull();
    expect(container.querySelector(".option a")).toBeNull();
    expect(container.querySelector(".statement")?.textContent).toContain("<img src=x");
  });

  it("al elegir una opción envía la letra, bloquea las opciones y detiene el reloj", () => {
    const { onAnswer, advance } = show(question());

    click(container.querySelector('[data-label="B"]'));
    click(container.querySelector('[data-label="C"]')); // segundo clic: ignorado

    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith("B");
    expect([...container.querySelectorAll<HTMLButtonElement>(".option")].every((b) => b.disabled)).toBe(true);

    advance(120_000);
    expect(onAnswer).toHaveBeenCalledTimes(1); // el vencimiento no envía otra vez
  });

  it("al llegar a cero envía la respuesta vacía una sola vez", () => {
    const { onAnswer, advance } = show(question());

    advance(89_000);
    expect(onAnswer).not.toHaveBeenCalled();
    advance(2_000);

    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith(null);
    expect(container.querySelector(".timer")?.textContent).toBe("0:00");
    expect(container.textContent).toContain("Se acabó el tiempo");
  });

  it("al recargar muestra el tiempo que queda, no 90 s", () => {
    // La pregunta se emitió hace 40 s según el servidor.
    show(question({ server_now: "2026-10-12T12:00:40Z", deadline_at: "2026-10-12T12:01:30Z" }),
      Date.parse("2026-10-12T12:00:40Z") - BASE_NOW);

    expect(container.querySelector(".timer")?.textContent).toBe("0:50");
  });

  it("corrige un reloj de cliente adelantado", () => {
    // El cliente está 30 s adelantado: sin corrección vería 1:00.
    now = BASE_NOW + 30_000;
    show(question(), -30_000);

    expect(container.querySelector(".timer")?.textContent).toBe("1:30");
  });

  it("anuncia el tiempo restante a lectores de pantalla solo en los umbrales", () => {
    const { advance } = show(question());
    const live = container.querySelector(".sr-only[aria-live]")!;

    advance(40_000);
    expect(live.textContent).toBe("");
    advance(20_000);
    expect(live.textContent).toBe("Quedan 30 segundos");
  });

  it("la limpieza detiene el cronómetro", () => {
    const { onAnswer, stop, advance } = show(question());

    stop();
    advance(120_000);

    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("no hay ninguna clave de respuesta en el DOM de la pregunta", () => {
    show(question());

    expect(container.innerHTML.toLowerCase()).not.toContain("correct");
  });
});

// --- resultado -------------------------------------------------------------------------

describe("pantalla de resultado", () => {
  function attempt(overrides: Partial<Attempt> = {}): Attempt {
    return {
      position: 1, selected_option: "B", is_correct: false, timed_out: false,
      time_used_ms: 12_340, correct_option: "A", area: "microeconomia", source_number: 57, ...overrides,
    };
  }

  function render(a: Attempt, isLast = false) {
    const container = document.createElement("div");
    const onNext = vi.fn();
    renderResult(container, { question: question(), attempt: a, isLast, onNext });
    return { container, onNext };
  }

  it("la revisión muestra la elegida y la correcta, y el banner el tiempo", () => {
    const { container } = render(attempt());

    expect(container.querySelector(".banner")?.textContent).toContain("Incorrecto");
    expect(container.textContent).toContain("B. Dos");
    expect(container.textContent).toContain("A. Uno");
    expect(container.textContent).toContain("12,3 s");
  });

  it("distingue acierto y vencimiento", () => {
    expect(render(attempt({ selected_option: "A", is_correct: true })).container.querySelector(".banner")?.textContent)
      .toContain("¡Correcto!");
    const timeout = render(attempt({ selected_option: null, timed_out: true, time_used_ms: 90_000 })).container;
    expect(timeout.querySelector(".banner")?.textContent).toContain("Se acabó el tiempo");
    expect(timeout.textContent).toContain("Sin respuesta");
  });

  it("muestra la referencia del PDF (área + número), no la posición ni ningún id", () => {
    const { container } = render(attempt({ area: "historia_pensamiento", source_number: 112 }));
    const reference = container.querySelector(".source-ref")?.textContent ?? "";

    expect(reference).toContain("Historia y Pensamiento Económico 112");
    expect(reference).not.toMatch(/Pregunta 1|[0-9a-f]{8}-[0-9a-f]{4}/);
  });

  it("repite el enunciado y las opciones, marcando en texto la elegida y la correcta", () => {
    const { container } = render(attempt({ selected_option: "B" }));

    expect(container.querySelector(".review .statement")?.textContent).toBe("¿Qué es el PIB?");
    const items = [...container.querySelectorAll(".review-option")];
    expect(items.map((li) => li.getAttribute("data-label"))).toEqual(["A", "B", "C"]);
    const byLabel = (l: string) => container.querySelector(`.review-option[data-label="${l}"]`)!;
    expect(byLabel("B").classList.contains("chosen")).toBe(true);
    expect(byLabel("B").textContent).toContain("✗ Tu respuesta");
    expect(byLabel("A").classList.contains("correct")).toBe(true);
    expect(byLabel("A").textContent).toContain("✓ Correcta");
    expect(byLabel("C").querySelector(".tags")).toBeNull();
  });

  it("si acertó, la opción lleva las dos marcas; si venció, solo la correcta", () => {
    const hit = render(attempt({ selected_option: "A", is_correct: true })).container;
    const hitText = hit.querySelector('.review-option[data-label="A"]')!.textContent;
    expect(hitText).toContain("✓ Tu respuesta");
    expect(hitText).toContain("✓ Correcta");

    const timeout = render(attempt({ selected_option: null, timed_out: true, time_used_ms: 90_000 })).container;
    expect(timeout.querySelector(".review-option.chosen")).toBeNull();
    expect(timeout.querySelector(".review-option.correct")).not.toBeNull();
    expect(timeout.querySelector(".source-ref")?.textContent).toContain("Microeconomía 57");
  });

  it("la revisión dibuja la figura de la pregunta con el cargador autenticado", async () => {
    const ref = "assets/cane-2026-econometria-006-fig-01.png";
    const loadFigure = vi.fn().mockResolvedValue("blob:http://localhost/figura");
    const container = document.createElement("div");
    renderResult(container, {
      question: question({
        statement_md: `Observe:\n\n![serie](${ref})\n\n![ajena](https://evil.test/p.png)`,
        assets: [{ ref, kind: "figure", alt: "Serie", source_page: 3, status: "available" }],
      }),
      attempt: attempt(), isLast: false, onNext: vi.fn(), loadFigure,
    });

    const images = container.querySelectorAll(".review img");
    expect(images).toHaveLength(1);
    await vi.waitFor(() => expect(images[0]!.getAttribute("src")).toBe("blob:http://localhost/figura"));
    expect(loadFigure).toHaveBeenCalledWith(ref);
    expect(container.innerHTML).not.toContain("evil.test");
  });

  it("la revisión pasa por el mismo sanitizado: el HTML del enunciado es texto", () => {
    const container = document.createElement("div");
    renderResult(container, {
      question: question({
        statement_md: '<img src=x onerror="alert(1)"><script>alert(2)</script> y una tabla:\n\n| a | b |\n|---|---|\n| 1 | 2 |',
        options: [
          { label: "A", text_md: "<b>negrita</b>" }, { label: "B", text_md: "$x^2$" }, { label: "C", text_md: "tres" },
        ],
      }),
      attempt: attempt(), isLast: false, onNext: vi.fn(),
    });

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".review-option b")).toBeNull();
    expect(container.querySelector(".review .rich-table table td")?.textContent).toBe("1");
    expect(container.querySelector('.review-option[data-label="B"] .katex')).not.toBeNull();
  });

  it("ya no hay caja intermedia ni botón antes de la revisión: un único botón, al final", () => {
    const { container } = render(attempt());

    expect(container.querySelector("dl.facts")).toBeNull();
    expect(container.textContent).not.toContain("Tiempo usado");
    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(1);
    const main = container.querySelector("main")!;
    expect(main.lastElementChild).toBe(buttons[0]); // después de la revisión
    expect(container.querySelector(".review")!.compareDocumentPosition(buttons[0]!)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("el tiempo usado va en una línea pequeña dentro del banner", () => {
    const { container } = render(attempt({ time_used_ms: 12_340 }));

    expect(container.querySelector(".banner .banner-detail")?.textContent).toBe("Tiempo: 12,3 s");
  });

  it("con tiempo agotado: banner claro, sin respuesta, la correcta marcada y un camino para seguir", () => {
    const { container } = render(
      attempt({ selected_option: null, is_correct: false, timed_out: true, time_used_ms: 90_000 }),
    );

    expect(container.querySelector(".banner.timeout .banner-title")?.textContent).toContain("Se acabó el tiempo");
    expect(container.querySelector(".banner-detail")?.textContent).toBe("Sin respuesta · Tiempo: 90,0 s");
    expect(container.querySelector(".review-option.chosen")).toBeNull();
    expect(container.querySelectorAll(".review-option.correct")).toHaveLength(1);
    expect(container.querySelector(".review-option.correct")?.textContent).toContain("✓ Correcta");
    expect(container.querySelector("button")?.textContent).toBe("Siguiente pregunta");
  });

  it("en la última pregunta el único botón conserva su texto ('Ver resumen')", () => {
    const { container } = render(attempt(), true);

    expect(container.querySelectorAll("button")).toHaveLength(1);
    expect(container.querySelector("button")?.textContent).toBe("Ver resumen");
  });

  it("el botón cambia en la última pregunta y avanza al pulsarlo", () => {
    const middle = render(attempt());
    const last = render(attempt(), true);

    expect(middle.container.querySelector("button")?.textContent).toBe("Siguiente pregunta");
    expect(last.container.querySelector("button")?.textContent).toBe("Ver resumen");
    click(last.container.querySelector("button"));
    expect(last.onNext).toHaveBeenCalledTimes(1);
  });
});

// --- logo -------------------------------------------------------------------------------------

describe("logo del CANE", () => {
  it("el encabezado muestra el logo con nombre accesible y sin texto duplicado", () => {
    const header = navBar(deps(vi.fn()), "home");
    const logo = header.querySelector(".brand img.brand-logo") as HTMLImageElement | null;

    expect(logo).not.toBeNull();
    expect(logo?.getAttribute("alt")).toBe("CANE Prep");
    expect(logo?.getAttribute("src")).toMatch(/logo_cane.*\.png$/);
    expect(header.querySelector(".brand")?.textContent).toBe(""); // el texto visible ya no está
    expect(header.querySelector("nav")?.textContent).not.toContain("CANE Prep");
  });

  it("el logo no se deforma: solo altura fija por CSS, ancho en automático", () => {
    const logo = navBar(deps(vi.fn()), "home").querySelector("img.brand-logo") as HTMLImageElement;

    expect(logo.getAttribute("width")).toBe("2172");
    expect(logo.getAttribute("height")).toBe("724"); // proporción 3:1 reservada; la altura real la fija el CSS
    expect(logo.getAttribute("style")).toBeNull();
  });

  it("el login usa el logo como título (h1), con el mismo nombre accesible", () => {
    const container = document.createElement("div");
    renderLogin(container, deps(vi.fn()));
    const h1 = container.querySelector("h1")!;

    expect(h1.querySelector("img")?.getAttribute("alt")).toBe("CANE Prep");
    expect(h1.textContent).toBe("");
    expect(h1.getAttribute("class")).toContain("login-brand");
  });
});

// --- resumen y ranking ---------------------------------------------------------------------

describe("resumen", () => {
  it("cuenta correctas, incorrectas y vencidas", () => {
    const base = {
      position: 1, selected_option: "A" as const, correct_option: "A" as const,
      area: "macroeconomia" as const, source_number: 12,
    };
    const stats = summarize([
      { ...base, is_correct: true, timed_out: false, time_used_ms: 2000 },
      { ...base, selected_option: "B", is_correct: false, timed_out: false, time_used_ms: 4000 },
      { ...base, selected_option: null, is_correct: false, timed_out: true, time_used_ms: 90_000 },
    ]);

    expect(stats).toEqual({ total: 3, correct: 1, wrong: 1, timedOut: 1, averageMs: 32_000 });
  });

  it("sin intentos no inventa un promedio", () => {
    expect(summarize([]).averageMs).toBeNull();
  });

  it("la tabla trae la referencia del PDF de cada pregunta y se puede deslizar", () => {
    const container = document.createElement("div");
    const attempt = (position: number, area: Attempt["area"], source_number: number): Attempt => ({
      position, selected_option: "A", is_correct: true, timed_out: false,
      time_used_ms: 3000, correct_option: "A", area, source_number,
    });
    renderSummary(container, deps(vi.fn()), { ...SESSION, status: "completed" }, [
      attempt(1, "microeconomia", 57),
      attempt(2, "historia_pensamiento", 3),
    ]);

    const rows = [...container.querySelectorAll("table.summary tbody tr")];
    expect(rows.map((r) => r.children[1]!.textContent)).toEqual([
      "Microeconomía 57", "Historia y Pensamiento Económico 3",
    ]);
    expect(rows.map((r) => r.children[0]!.textContent)).toEqual(["1", "2"]); // posición, aparte
    const region = container.querySelector('.table-scroll[role="region"]');
    expect(region?.getAttribute("tabindex")).toBe("0");
    expect(region?.querySelector("table.summary")).not.toBeNull();
  });
});

describe("ranking", () => {
  const row = (overrides: Partial<RankingRow>): RankingRow => ({
    display_name: "Ana", rank_position: 1, questions_seen: 25, correct_count: 20,
    accuracy_pct: 80, avg_time_seconds: 14.5, sessions_completed: 3, is_me: false, ...overrides,
  });

  it("indica cuántas preguntas faltan para tener puesto", () => {
    expect(positionLabel(row({ rank_position: 2 }))).toBe("2");
    expect(positionLabel(row({ rank_position: null, questions_seen: 5 }))).toBe("Faltan 15 preguntas");
    expect(positionLabel(row({ rank_position: null, questions_seen: 19 }))).toBe("Falta 1 pregunta");
  });

  it("resalta mi fila y muestra los nombres como texto", () => {
    const table = renderRankingTable([
      row({ display_name: "<b>Ana</b>" }),
      row({ display_name: "Yo", rank_position: 2, is_me: true }),
    ]);

    expect(table.querySelector("tr.me")?.textContent).toContain("Yo (tú)");
    expect(table.querySelector("b")).toBeNull();
    expect(table.textContent).toContain("<b>Ana</b>");
  });

  it("la tabla va en una región deslizable y conserva mi fila y el aviso de preguntas faltantes", () => {
    const table = renderRankingTable([
      row({ display_name: "Ana", rank_position: 1 }),
      row({ display_name: "Yo", rank_position: null, questions_seen: 7, is_me: true, accuracy_pct: 42.9 }),
    ]);

    const region = table.querySelector('.table-scroll[role="region"]');
    expect(region).not.toBeNull();
    expect(region?.getAttribute("tabindex")).toBe("0");
    expect(region?.querySelector("table.ranking")).not.toBeNull();
    expect(table.querySelector("tr.me")?.textContent).toContain("Faltan 13 preguntas");
    expect(table.querySelectorAll("thead th")).toHaveLength(6); // ninguna columna se pierde
    expect(table.querySelector(".scroll-hint")).not.toBeNull();
  });

  it("sin filas muestra un aviso", () => {
    expect(renderRankingTable([]).textContent).toContain("Todavía no hay datos");
  });
});
