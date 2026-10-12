import { ApiError } from "../api";
import type { Deps } from "../deps";
import { h } from "../dom";
import { describeFailure } from "../play";
import { hrefFor } from "../router";
import {
  AREA_LABELS,
  STAGE_LABELS,
  type Area,
  type CreateSessionInput,
  type Mode,
  type Stage,
} from "../types";
import { card, errorNotice, navBar } from "./layout";

/** Tope provisional del backend (MAX_QUESTIONS_PER_SESSION); no es una regla acordada. */
const MAX_QUESTIONS = 50;
const DEFAULT_QUESTIONS = 10;

const MODE_LABELS: Record<Mode, string> = {
  area: "Por área",
  random: "Aleatorio",
  simulacro: "Simulacro",
};

export async function renderHome(container: HTMLElement, deps: Deps): Promise<void> {
  const resume = h("div");
  const error = h("div");

  // --- formulario -------------------------------------------------------------
  const modeInputs = (Object.keys(MODE_LABELS) as Mode[]).map((mode, index) =>
    h("input", {
      type: "radio", name: "mode", value: mode, id: `mode-${mode}`,
      checked: index === 0, onchange: () => sync(),
    }),
  );
  const areaSelect = h(
    "select",
    { id: "area", name: "area" },
    ...(Object.keys(AREA_LABELS) as Area[]).map((a) => h("option", { value: a }, AREA_LABELS[a])),
  );
  const stageSelect = h(
    "select",
    { id: "stage", name: "stage" },
    ...(Object.keys(STAGE_LABELS) as Stage[]).map((s) => h("option", { value: s }, STAGE_LABELS[s])),
  );
  const countInput = h("input", {
    id: "question_count", name: "question_count", type: "number",
    min: 1, max: MAX_QUESTIONS, value: DEFAULT_QUESTIONS, inputmode: "numeric",
  });

  const areaField = h("div", { class: "field" }, h("label", { for: "area" }, "Área"), areaSelect);
  const stageField = h("div", { class: "field" }, h("label", { for: "stage" }, "Fase"), stageSelect);
  const countField = h(
    "div",
    { class: "field" },
    h("label", { for: "question_count" }, `Número de preguntas (1 a ${MAX_QUESTIONS})`),
    countInput,
  );
  const start = h("button", { type: "submit", class: "primary" }, "Empezar");

  function selectedMode(): Mode {
    const checked = modeInputs.find((input) => input.checked);
    return (checked?.value as Mode | undefined) ?? "area";
  }

  function sync(): void {
    const mode = selectedMode();
    areaField.hidden = mode !== "area";
    stageField.hidden = mode !== "simulacro";
    countField.hidden = mode === "simulacro";
  }

  function buildInput(): CreateSessionInput | string {
    const mode = selectedMode();
    if (mode === "simulacro") return { mode, stage: stageSelect.value as Stage };
    const count = Number(countInput.value);
    if (!Number.isInteger(count) || count < 1 || count > MAX_QUESTIONS) {
      return `El número de preguntas debe estar entre 1 y ${MAX_QUESTIONS}.`;
    }
    return mode === "area"
      ? { mode, area: areaSelect.value as Area, question_count: count }
      : { mode, question_count: count };
  }

  async function begin(): Promise<void> {
    error.replaceChildren();
    const input = buildInput();
    if (typeof input === "string") {
      error.replaceChildren(errorNotice(input));
      return;
    }
    start.disabled = true;
    try {
      const session = await deps.api.createSession(input);
      deps.store.set(session.id);
      deps.go({ name: "play", sessionId: session.id });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await deps.signOut("Tu sesión venció. Inicia sesión de nuevo.");
        return;
      }
      const message =
        e instanceof ApiError && e.status === 409
          ? "No hay suficientes preguntas disponibles para esa opción."
          : describeFailure(e).message;
      error.replaceChildren(errorNotice(message));
      start.disabled = false;
    }
  }

  const form = h(
    "form",
    {
      novalidate: true,
      onsubmit: (event: Event) => {
        event.preventDefault();
        void begin();
      },
    },
    h(
      "fieldset",
      null,
      h("legend", null, "Modo"),
      ...(Object.keys(MODE_LABELS) as Mode[]).map((mode, i) =>
        h("label", { class: "radio", for: `mode-${mode}` }, modeInputs[i]!, " ", MODE_LABELS[mode]),
      ),
    ),
    areaField,
    stageField,
    countField,
    error,
    start,
  );
  sync();

  container.replaceChildren(
    navBar(deps, "home"),
    h(
      "main",
      { class: "shell" },
      h("h1", null, "¿Qué quieres practicar?"),
      resume,
      card(form),
      h("p", null, h("a", { href: hrefFor({ name: "ranking" }) }, "Ver el ranking del equipo")),
    ),
  );

  // --- continuar sesión (id guardado en este navegador) -------------------------
  const storedId = deps.store.get();
  if (!storedId) return;
  try {
    const session = await deps.api.getSession(storedId);
    if (session.status !== "active") {
      deps.store.clear();
      return;
    }
    resume.replaceChildren(
      card(
        h("p", null, `Tienes una sesión en curso: ${session.answered_count} de ${session.question_count} respondidas.`),
        h(
          "button",
          {
            type: "button",
            class: "primary",
            onclick: () => deps.go({ name: "play", sessionId: session.id }),
          },
          "Continuar",
        ),
        " ",
        h(
          "button",
          {
            type: "button",
            onclick: async () => {
              try {
                await deps.api.abandon(session.id);
              } catch {
                /* si ya estaba cerrada, da igual */
              }
              deps.store.clear();
              resume.replaceChildren();
            },
          },
          "Abandonarla",
        ),
      ),
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) deps.store.clear();
    if (e instanceof ApiError && e.status === 401) {
      await deps.signOut("Tu sesión venció. Inicia sesión de nuevo.");
    }
    // otros fallos: simplemente no se ofrece continuar
  }
}
