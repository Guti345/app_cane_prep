import { h } from "../dom";
import { renderRichInline } from "../richtext";
import type { Attempt, OptionLabel, Question } from "../types";
import { card, formatSeconds } from "./layout";

export interface ResultViewProps {
  question: Question;
  attempt: Attempt;
  isLast: boolean;
  onNext(): void;
}

function optionContent(question: Question, label: OptionLabel | null): Node {
  if (label === null) return document.createTextNode("sin respuesta");
  const option = question.options.find((o) => o.label === label);
  if (!option) return document.createTextNode(label);
  return h("span", { class: "rich" }, `${label}. `, renderRichInline(option.text_md));
}

export function renderResult(container: HTMLElement, props: ResultViewProps): void {
  const { attempt, question } = props;
  const state = attempt.timed_out ? "timeout" : attempt.is_correct ? "ok" : "bad";
  const title = attempt.timed_out
    ? "Se acabó el tiempo"
    : attempt.is_correct
      ? "¡Correcto!"
      : "Incorrecto";

  const next = h(
    "button",
    { type: "button", class: "primary", onclick: () => props.onNext() },
    props.isLast ? "Ver resumen" : "Siguiente pregunta",
  );

  container.replaceChildren(
    h(
      "main",
      { class: "shell" },
      h("p", { class: "muted" }, `Pregunta ${question.position}`),
      h("div", { class: `banner ${state}`, role: "status" }, title),
      card(
        h(
          "dl",
          { class: "facts" },
          h("dt", null, "Tu respuesta"),
          h("dd", null, optionContent(question, attempt.selected_option)),
          h("dt", null, "Respuesta correcta"),
          h("dd", null, optionContent(question, attempt.correct_option)),
          h("dt", null, "Tiempo usado"),
          h("dd", null, formatSeconds(attempt.time_used_ms)),
        ),
      ),
      next,
    ),
  );
  next.focus();
}
