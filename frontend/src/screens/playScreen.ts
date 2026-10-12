import type { Deps } from "../deps";
import { h } from "../dom";
import { PlayController, type PlayState } from "../play";
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

  const controller = new PlayController(
    deps.api,
    (state) => {
      if (!disposed) show(state);
    },
    now,
  );

  function show(state: PlayState): void {
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
        });
        break;

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
  };
}
