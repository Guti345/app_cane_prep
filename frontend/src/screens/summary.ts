import type { Deps } from "../deps";
import { h } from "../dom";
import { hrefFor } from "../router";
import type { Attempt, Session } from "../types";
import { card, formatSeconds, navBar } from "./layout";

export interface SummaryStats {
  total: number;
  correct: number;
  wrong: number;
  timedOut: number;
  averageMs: number | null;
}

export function summarize(attempts: Attempt[]): SummaryStats {
  const timedOut = attempts.filter((a) => a.timed_out).length;
  const correct = attempts.filter((a) => a.is_correct).length;
  const totalMs = attempts.reduce((sum, a) => sum + a.time_used_ms, 0);
  return {
    total: attempts.length,
    correct,
    wrong: attempts.length - correct - timedOut,
    timedOut,
    averageMs: attempts.length ? totalMs / attempts.length : null,
  };
}

export function renderSummary(
  container: HTMLElement,
  deps: Deps,
  session: Session,
  attempts: Attempt[],
): void {
  const stats = summarize(attempts);
  const abandoned = session.status === "abandoned";

  container.replaceChildren(
    navBar(deps, "none"),
    h(
      "main",
      { class: "shell" },
      h("h1", null, abandoned ? "Sesión abandonada" : "Resumen de la sesión"),
      card(
        h(
          "dl",
          { class: "facts" },
          h("dt", null, "Respondidas"),
          h("dd", null, `${stats.total} de ${session.question_count}`),
          h("dt", null, "Correctas"),
          h("dd", null, stats.correct),
          h("dt", null, "Incorrectas"),
          h("dd", null, stats.wrong),
          h("dt", null, "Sin tiempo"),
          h("dd", null, stats.timedOut),
          h("dt", null, "Tiempo promedio"),
          h("dd", null, stats.averageMs === null ? "—" : formatSeconds(stats.averageMs)),
        ),
      ),
      attempts.length
        ? card(
            h(
              "table",
              { class: "table" },
              h("caption", { class: "sr-only" }, "Resultado por pregunta"),
              h(
                "thead",
                null,
                h(
                  "tr",
                  null,
                  h("th", { scope: "col" }, "#"),
                  h("th", { scope: "col" }, "Tu respuesta"),
                  h("th", { scope: "col" }, "Correcta"),
                  h("th", { scope: "col" }, "Resultado"),
                  h("th", { scope: "col" }, "Tiempo"),
                ),
              ),
              h(
                "tbody",
                null,
                ...attempts.map((a) =>
                  h(
                    "tr",
                    null,
                    h("td", null, a.position),
                    h("td", null, a.selected_option ?? "—"),
                    h("td", null, a.correct_option),
                    h("td", null, a.timed_out ? "Sin tiempo" : a.is_correct ? "Correcta" : "Incorrecta"),
                    h("td", null, formatSeconds(a.time_used_ms)),
                  ),
                ),
              ),
            ),
          )
        : null,
      h(
        "p",
        null,
        h("a", { class: "button primary", href: hrefFor({ name: "home" }) }, "Nueva sesión"),
        " ",
        h("a", { class: "button", href: hrefFor({ name: "ranking" }) }, "Ver ranking"),
      ),
    ),
  );
}
