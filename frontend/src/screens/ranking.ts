import { ApiError } from "../api";
import type { Deps } from "../deps";
import { describeFailure } from "../play";
import { h } from "../dom";
import { MIN_QUESTIONS_FOR_RANKING, type RankingRow } from "../types";
import { card, errorNotice, formatSeconds, navBar, scrollRegion } from "./layout";

export function positionLabel(row: RankingRow): string {
  if (row.rank_position !== null) return String(row.rank_position);
  const missing = Math.max(0, MIN_QUESTIONS_FOR_RANKING - row.questions_seen);
  return missing === 1 ? "Falta 1 pregunta" : `Faltan ${missing} preguntas`;
}

export function renderRankingTable(rows: RankingRow[]): HTMLElement {
  if (rows.length === 0) {
    return h("p", { class: "muted" }, "Todavía no hay datos en el ranking.");
  }
  const table = h(
    "table",
    { class: "table ranking" },
    h("caption", { class: "sr-only" }, "Ranking del equipo"),
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { scope: "col" }, "Puesto"),
        h("th", { scope: "col" }, "Nombre"),
        h("th", { scope: "col" }, "Precisión"),
        h("th", { scope: "col" }, "Tiempo promedio"),
        h("th", { scope: "col" }, "Preguntas"),
        h("th", { scope: "col" }, "Aciertos"),
      ),
    ),
    h(
      "tbody",
      null,
      ...rows.map((row) =>
        h(
          "tr",
          { class: row.is_me ? "me" : undefined },
          h("td", null, positionLabel(row)),
          h("td", null, row.display_name, row.is_me ? " (tú)" : null),
          h("td", null, row.accuracy_pct === null ? "—" : `${row.accuracy_pct.toFixed(1).replace(".", ",")} %`),
          h("td", null, row.avg_time_seconds === null ? "—" : formatSeconds(row.avg_time_seconds * 1000)),
          h("td", null, row.questions_seen),
          h("td", null, row.correct_count),
        ),
      ),
    ),
  );
  return h(
    "div",
    null,
    h("p", { class: "scroll-hint muted small" }, "Desliza la tabla hacia los lados para ver todas las columnas."),
    scrollRegion("Ranking del equipo (se desliza hacia los lados)", table),
  );
}

export async function renderRanking(container: HTMLElement, deps: Deps): Promise<void> {
  const body = h("div", null, h("p", { class: "muted", role: "status" }, "Cargando…"));
  container.replaceChildren(
    navBar(deps, "ranking"),
    h(
      "main",
      { class: "shell" },
      h("h1", null, "Ranking del equipo"),
      h(
        "p",
        { class: "muted" },
        `Se ordena por precisión y, a igualdad, por menor tiempo promedio. Aparecen con puesto quienes tienen al menos ${MIN_QUESTIONS_FOR_RANKING} preguntas distintas.`,
      ),
      card(body),
    ),
  );

  try {
    const rows = await deps.api.ranking();
    body.replaceChildren(renderRankingTable(rows));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await deps.signOut("Tu sesión venció. Inicia sesión de nuevo.");
      return;
    }
    body.replaceChildren(errorNotice(describeFailure(error).message));
  }
}
