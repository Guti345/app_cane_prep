import type { Deps } from "../deps";
import { h } from "../dom";
import { PlayController, type PlayState } from "../play";
import type { FigureLoader } from "../richtext";
import type { Question, Session } from "../types";
import { hrefFor } from "../router";
import { renderQuestion } from "./question";
import { renderResult } from "./result";
import { renderSummary } from "./summary";
import { card, navBar } from "./layout";

/** Orquesta pregunta → resultado → … → resumen. Devuelve la limpieza. */
export function renderPlayScreen(
  container: HTMLElement,
  deps: Deps,
  sessionId: string,
  now?: () => number,
): () => void {
  let stopTimer: () => void = () => {};
  let disposed = false;
  // Figuras de la pregunta en pantalla: URLs locales (blob:) que se liberan al cambiar de pantalla.
  let figureUrls: string[] = [];
  const releaseFigures = (): void => {
    for (const url of figureUrls) URL.revokeObjectURL(url);
    figureUrls = [];
  };

  const controller = new PlayController(
    deps.api,
    (state) => {
      if (!disposed) show(state);
    },
    now,
  );

  /** Pide la figura a la API con la sesión del usuario y devuelve una URL local (blob:). */
  function figureLoaderFor(session: Session, question: Question): FigureLoader {
    return async (ref) => {
      const blob = await deps.api.figure(session.id, question.position, ref.replace(/^assets\//, ""));
      if (disposed) throw new Error("pantalla cerrada");
      const url = URL.createObjectURL(blob);
      figureUrls.push(url);
      return url;
    };
  }

  function show(state: PlayState): void {
    if (state.kind !== "submitting") releaseFigures();
    switch (state.kind) {
      case "loading":
        stopTimer();
        container.replaceChildren(
          h("main", { class: "shell" }, h("p", { class: "muted", role: "status" }, "Cargando…")),
        );
        break;

      case "question":
        stopTimer();
        deps.store.set(state.session.id);
        stopTimer = renderQuestion(container, {
          session: state.session,
          question: state.question,
          offsetMs: state.offsetMs,
          now,
          loadFigure: figureLoaderFor(state.session, state.question),
          onAnswer: (option) => void controller.submit(option),
          onAbandon: () => void controller.abandon(),
        });
        break;

      case "submitting":
        // La vista de la pregunta ya muestra "Enviando…" y bloqueó las opciones.
        break;

      case "result":
        stopTimer();
        renderResult(container, {
          question: state.question,
          attempt: state.attempt,
          isLast: state.isLast,
          onNext: () => void controller.continue(),
          loadFigure: figureLoaderFor(state.session, state.question),
        });
        break;

      case "unconfirmed": {
        stopTimer();
        const chosen = state.option ?? "sin respuesta";
        const missing = state.saved === "missing";
        container.replaceChildren(
          navBar(deps, "none"),
          h(
            "main",
            { class: "shell" },
            card(
              h(
                "p",
                { class: "notice error", role: "alert" },
                missing
                  ? "Tu respuesta no llegó al servidor y no quedó registrada."
                  : "No pudimos confirmar si tu respuesta quedó registrada.",
              ),
              h(
                "p",
                { class: "muted" },
                missing
                  ? `Puedes reenviarla (${chosen}). El plazo lo controla el servidor: si ya venció, se registrará como sin respuesta.`
                  : "Primero comprobamos qué guardó el servidor; no la reenviamos a ciegas.",
              ),
              missing
                ? h(
                    "button",
                    { type: "button", class: "primary", onclick: () => void controller.resendAnswer() },
                    "Reenviar mi respuesta",
                  )
                : h(
                    "button",
                    { type: "button", class: "primary", onclick: () => void controller.checkAnswer() },
                    "Comprobar de nuevo",
                  ),
              " ",
              h("a", { class: "button", href: hrefFor({ name: "home" }) }, "Ir al inicio"),
            ),
          ),
        );
        break;
      }

      case "summary":
        stopTimer();
        deps.store.clear();
        renderSummary(container, deps, state.session, state.attempts);
        break;

      case "error":
        stopTimer();
        if (state.reason === "auth") {
          void deps.signOut(state.message);
          break;
        }
        if (state.reason === "notfound") deps.store.clear();
        container.replaceChildren(
          navBar(deps, "none"),
          h(
            "main",
            { class: "shell" },
            card(
              h("p", { class: "notice error", role: "alert" }, state.message),
              state.reason === "unavailable" || state.reason === "unexpected"
                ? h(
                    "button",
                    { type: "button", class: "primary", onclick: () => void controller.retry() },
                    "Reintentar",
                  )
                : null,
              " ",
              h("a", { class: "button", href: hrefFor({ name: "home" }) }, "Ir al inicio"),
            ),
          ),
        );
        break;
    }
  }

  void controller.open(sessionId);
  return () => {
    disposed = true;
    stopTimer();
    releaseFigures();
  };
}
