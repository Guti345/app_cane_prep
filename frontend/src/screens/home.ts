import { ApiError, isUncertainOutcome } from "../api";
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
  // Al abrir el inicio no hay una pregunta en curso: es el momento de despertar el servidor
  // (una sola petición, solo si pasaron más de 10 min sin respuesta). No se espera aquí.
  void deps.api.warmUp();
  // Resultado incierto de una creación anterior (persistente, ligado al usuario).
  const pendingBox = h("div");

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
  // Deshabilitado hasta saber si hay una creación incierta pendiente de este usuario.
  const start = h("button", { type: "submit", class: "primary", disabled: true }, "Empezar");

  /** Muestra el bloqueo (si lo hay) y habilita o no "Empezar". Devuelve si hay bloqueo. */
  async function applyPending(): Promise<boolean> {
    const userId = await deps.auth.getUserId();
    const pending = userId ? deps.pendingCreate.get(userId) : null;
    if (!userId || !pending) {
      pendingBox.replaceChildren();
      start.disabled = false;
      return false;
    }
    start.disabled = true;
    if (!deps.pendingCreate.holdElapsed(pending)) {
      const minutes = Math.ceil(deps.pendingCreate.remainingMs(pending) / 60_000);
      const until = new Date(deps.pendingCreate.releasableAt(pending));
      pendingBox.replaceChildren(
        h(
          "div",
          { class: "notice error", role: "alert" },
          h("p", null,
            "Una creación de sesión quedó sin confirmar: la respuesta del servidor no llegó, " +
              "así que pudo crearse una sesión que esta pantalla no puede mostrar. " +
              "Para no duplicarla, «Empezar» está bloqueado."),
          h("p", { class: "muted" },
            "Recargar la página o volver a iniciar sesión no lo resuelve. Podrás continuar a partir de las " +
              `${until.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })} ` +
              `(faltan unos ${minutes} min), cuando la petición original ya no pueda completarse.`),
        ),
      );
      return true;
    }
    pendingBox.replaceChildren(
      h(
        "div",
        { class: "notice error", role: "alert" },
        h("p", null,
          "Quedó sin confirmar una creación de sesión y ya pasó el tiempo en que podía completarse. " +
            "Con la API actual no podemos comprobar si se creó: una sesión sin respuestas no entra " +
            "en el ranking, pero no la verás aquí."),
        h("button", {
          type: "button",
          onclick: () => {
            deps.pendingCreate.clear(userId);
            void applyPending();
          },
        }, "Entiendo que pudo quedar una sesión sin usar; permitir crear otra"),
      ),
    );
    return true;
  }

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
    // Por teclado (Enter) se puede enviar el formulario aunque el botón esté deshabilitado.
    if (await applyPending()) return;
    const userId = await deps.auth.getUserId();
    if (!userId) {
      await deps.signOut("Tu sesión venció. Inicia sesión de nuevo.");
      return;
    }
    start.disabled = true;
    try {
      // La marca se escribe justo ANTES de enviar: una recarga con la petición en vuelo
      // deja el bloqueo. Solo un resultado definitivo la borra.
      const session = await deps.api.createSession(input, {
        beforeSend: () => deps.pendingCreate.set(userId),
      });
      deps.pendingCreate.clear(userId);
      deps.store.set(session.id);
      deps.go({ name: "play", sessionId: session.id });
    } catch (e) {
      if (isUncertainOutcome(e)) {
        // POST /sessions no es idempotente y no hay endpoint para recuperar una sesión
        // sin conocer su id: repetirlo a ciegas podría crear una segunda.
        deps.pendingCreate.set(userId);
        await applyPending();
        return;
      }
      // Resultado definitivo (no se envió, o el servidor rechazó con un 4xx): nada se creó.
      deps.pendingCreate.clear(userId);
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
      pendingBox,
      card(form),
      h("p", null, h("a", { href: hrefFor({ name: "ranking" }) }, "Ver el ranking del equipo")),
    ),
  );

  await applyPending();

  // --- continuar sesión (id guardado en este navegador) -------------------------
  // Esto es solo comodidad: encontrar una sesión activa NO borra el bloqueo, porque no
  // demuestra que sea la de la petición perdida.
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
