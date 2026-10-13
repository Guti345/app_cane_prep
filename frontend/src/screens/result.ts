import { h } from "../dom";
import { hydrateFigures, renderRich, renderRichInline, type FigureLoader } from "../richtext";
import type { Attempt, OptionLabel, Question, QuestionOption } from "../types";
import { card, formatSeconds, sourceReference } from "./layout";

export interface ResultViewProps {
  question: Question;
  attempt: Attempt;
  isLast: boolean;
  onNext(): void;
  /** Obtiene una figura (blob:) por su ref; sin él, las figuras no se cargan. */
  loadFigure?: FigureLoader;
}

function optionContent(question: Question, label: OptionLabel | null): Node {
  if (label === null) return document.createTextNode("sin respuesta");
  const option = question.options.find((o) => o.label === label);
  if (!option) return document.createTextNode(label);
  return h("span", { class: "rich" }, `${label}. `, renderRichInline(option.text_md));
}

/** Una opción de la revisión, con marcas en texto (no solo color) de la elegida y la correcta. */
function reviewOption(option: QuestionOption, attempt: Attempt): HTMLElement {
  const chosen = attempt.selected_option === option.label;
  const correct = attempt.correct_option === option.label;
  const classes = ["review-option", chosen ? "chosen" : "", correct ? "correct" : ""].filter(Boolean);
  return h(
    "li",
    { class: classes.join(" "), "data-label": option.label },
    h("span", { class: "option-label" }, `${option.label}.`),
    " ",
    h("span", { class: "option-text rich" }, renderRichInline(option.text_md)),
    chosen || correct
      ? h(
          "span",
          { class: "tags" },
          chosen ? h("span", { class: `tag ${correct ? "correct" : "wrong"}` }, correct ? "✓ Tu respuesta" : "✗ Tu respuesta") : null,
          correct ? h("span", { class: "tag correct" }, "✓ Correcta") : null,
        )
      : null,
  );
}

export function renderResult(container: HTMLElement, props: ResultViewProps): void {
  const { attempt, question } = props;
  const state = attempt.timed_out ? "timeout" : attempt.is_correct ? "ok" : "bad";
  const title = attempt.timed_out
    ? "⏱ Se acabó el tiempo"
    : attempt.is_correct
      ? "✓ ¡Correcto!"
      : "✗ Incorrecto";

  const next = (): HTMLButtonElement =>
    h(
      "button",
      { type: "button", class: "primary", onclick: () => props.onNext() },
      props.isLast ? "Ver resumen" : "Siguiente pregunta",
    );
  const top = next();

  const statement = h(
    "div",
    { class: "statement rich" },
    renderRich(question.statement_md, { assets: question.assets }),
  );
  if (props.loadFigure) hydrateFigures(statement, props.loadFigure);

  container.replaceChildren(
    h(
      "main",
      { class: "shell" },
      h("p", { class: "muted" }, `Pregunta ${question.position}`),
      h("div", { class: `banner ${state}`, role: "status" }, title),
      card(
        h(
          "dl",
          { class: "facts stacked" },
          h("dt", null, "Tu respuesta"),
          h("dd", null, optionContent(question, attempt.selected_option)),
          h("dt", null, "Respuesta correcta"),
          h("dd", null, optionContent(question, attempt.correct_option)),
          h("dt", null, "Tiempo usado"),
          h("dd", null, formatSeconds(attempt.time_used_ms)),
        ),
      ),
      top,
      h(
        "section",
        { class: "card review", "aria-labelledby": "review-title" },
        h("h2", { id: "review-title" }, "Revisión de la pregunta"),
        h(
          "p",
          { class: "source-ref" },
          "Para repasarla en el PDF del banco: ",
          h("strong", null, sourceReference(attempt)),
        ),
        statement,
        h(
          "ul",
          { class: "review-options", "aria-label": "Opciones" },
          ...question.options.map((option) => reviewOption(option, attempt)),
        ),
      ),
      next(),
    ),
  );
  // Sin desplazar: la revisión puede ser larga y el aviso de arriba debe quedar a la vista.
  top.focus({ preventScroll: true });
}
