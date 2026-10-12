import { h } from "../dom";
import { announcement, formatClock, startCountdown } from "../timer";
import { AREA_LABELS, QUESTION_SECONDS, type OptionLabel, type Question, type Session } from "../types";
import { card } from "./layout";

export interface QuestionViewProps {
  session: Session;
  question: Question;
  /** Servidor − cliente, en ms (ver timer.clockOffset). */
  offsetMs: number;
  /** `null` registra el vencimiento. */
  onAnswer(option: OptionLabel | null): void;
  onAbandon(): void;
  now?: () => number;
}

/**
 * Pregunta con cuenta atrás. El tiempo mostrado sale del plazo del servidor;
 * al llegar a cero se envía la respuesta vacía y el servidor decide.
 * Devuelve la función que detiene el cronómetro.
 */
export function renderQuestion(container: HTMLElement, props: QuestionViewProps): () => void {
  const { question, session } = props;
  let settled = false;

  const clock = h("div", { class: "timer", "aria-hidden": "true" }, formatClock(QUESTION_SECONDS));
  const bar = h("div", { class: "timer-bar-fill" });
  const live = h("p", { class: "sr-only", role: "status", "aria-live": "polite" });
  const status = h("p", { class: "notice", role: "status", "aria-live": "polite" });

  const buttons = question.options.map((option) =>
    h(
      "button",
      {
        type: "button",
        class: "option",
        "data-label": option.label,
        onclick: () => choose(option.label),
      },
      h("span", { class: "option-label" }, `${option.label}.`),
      " ",
      option.text_md,
    ),
  );

  function lock(message: string): void {
    settled = true;
    countdown.stop();
    for (const button of buttons) button.disabled = true;
    status.textContent = message;
  }

  function choose(label: OptionLabel): void {
    if (settled) return;
    lock("Enviando respuesta…");
    props.onAnswer(label);
  }

  const deadlineMs = Date.parse(question.deadline_at);
  const countdown = startCountdown({
    deadlineMs,
    offsetMs: props.offsetMs,
    now: props.now,
    onTick(seconds, remaining) {
      clock.textContent = formatClock(seconds);
      clock.classList.toggle("urgent", seconds <= 10);
      bar.style.width = `${Math.min(100, (remaining / (QUESTION_SECONDS * 1000)) * 100)}%`;
      const spoken = announcement(seconds);
      if (spoken && live.textContent !== spoken) live.textContent = spoken;
    },
    onExpire() {
      if (settled) return;
      lock("Se acabó el tiempo. Registrando…");
      props.onAnswer(null);
    },
  });

  container.replaceChildren(
    h(
      "main",
      { class: "shell" },
      h(
        "div",
        { class: "question-head" },
        h(
          "p",
          { class: "muted" },
          `Pregunta ${question.position} de ${session.question_count} · ${AREA_LABELS[question.area]}`,
        ),
        clock,
      ),
      h("div", { class: "timer-bar", "aria-hidden": "true" }, bar),
      live,
      card(
        h("p", { class: "statement" }, question.statement_md),
        h("div", { class: "options", role: "group", "aria-label": "Opciones de respuesta" }, ...buttons),
        status,
      ),
      h(
        "button",
        {
          type: "button",
          class: "link",
          onclick: () => {
            if (!settled && window.confirm("¿Abandonar esta sesión?")) {
              lock("Abandonando…");
              props.onAbandon();
            }
          },
        },
        "Abandonar sesión",
      ),
    ),
  );

  return () => countdown.stop();
}
