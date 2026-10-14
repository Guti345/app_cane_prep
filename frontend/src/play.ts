/**
 * Máquina de estados de una sesión de juego. No toca el DOM: recibe la API y
 * emite estados; las pantallas solo los dibujan.
 *
 * Recargar siempre se resuelve preguntando al servidor: `open` pide el estado
 * y `nextQuestion`, que devuelve la pregunta pendiente con el mismo plazo.
 */
import { ApiError, isUncertainOutcome, type ApiClient } from "./api";
import { clockOffset } from "./timer";
import type { Attempt, OptionLabel, Question, Session } from "./types";

export type FailureReason = "auth" | "forbidden" | "notfound" | "unavailable" | "unexpected";

export type PlayState =
  | { kind: "loading" }
  | { kind: "question"; session: Session; question: Question; offsetMs: number }
  | { kind: "submitting"; session: Session; question: Question }
  | { kind: "result"; session: Session; question: Question; attempt: Attempt; isLast: boolean }
  /**
   * La respuesta se envió pero no llegó su resultado. `missing`: el servidor confirmó que NO
   * la guardó (se puede reenviar la misma posición); `unknown`: no se pudo comprobar, y un
   * GET fallido no equivale a "no se guardó".
   */
  | {
      kind: "unconfirmed";
      session: Session;
      question: Question;
      option: OptionLabel | null;
      saved: "unknown" | "missing";
    }
  | { kind: "summary"; session: Session; attempts: Attempt[] }
  | { kind: "error"; reason: FailureReason; message: string };

export function describeFailure(error: unknown): { reason: FailureReason; message: string } {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return { reason: "auth", message: "Tu sesión venció. Inicia sesión de nuevo." };
    }
    if (error.status === 403) {
      return {
        reason: "forbidden",
        message: "Tu usuario no tiene un equipo asignado. Avisa al administrador.",
      };
    }
    if (error.status === 404) {
      return { reason: "notfound", message: "Esa sesión ya no existe." };
    }
    if (error.status === 0 || error.status === 503) {
      return { reason: "unavailable", message: "No se pudo conectar con el servidor." };
    }
  }
  return { reason: "unexpected", message: "Ocurrió un error inesperado." };
}

export class PlayController {
  private sessionId: string | null = null;
  private session: Session | null = null;
  private question: Question | null = null;
  private answered = 0;
  private busy = false;
  /** Respuesta enviada cuyo resultado no conocemos (ver estado `unconfirmed`). */
  private uncertain: {
    session: Session;
    question: Question;
    option: OptionLabel | null;
    missing: boolean;
  } | null = null;

  constructor(
    private readonly api: ApiClient,
    private readonly emit: (state: PlayState) => void,
    private readonly now: () => number = Date.now,
  ) {}

  /** Abre una sesión: retoma la pregunta pendiente o muestra el resumen. */
  async open(sessionId: string): Promise<void> {
    this.sessionId = sessionId; // para poder reintentar aunque falle el primer GET
    this.emit({ kind: "loading" });
    try {
      const session = await this.api.getSession(sessionId);
      this.session = session;
      this.answered = session.answered_count;
      if (session.status !== "active") {
        await this.showSummary();
        return;
      }
      await this.loadQuestion();
    } catch (error) {
      this.fail(error);
    }
  }

  /** Reintenta tras un fallo de conexión. */
  async retry(): Promise<void> {
    if (this.sessionId) await this.open(this.sessionId);
  }

  async submit(option: OptionLabel | null): Promise<void> {
    const session = this.session;
    const question = this.question;
    if (this.busy || !session || !question) return;
    this.busy = true;
    this.emit({ kind: "submitting", session, question });
    try {
      const attempt = await this.api.answer(session.id, {
        position: question.position,
        selected_option: option,
      });
      this.answered += 1;
      this.question = null;
      this.uncertain = null;
      this.emit({
        kind: "result",
        session,
        question,
        attempt,
        isLast: this.answered >= session.question_count,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        this.busy = false;
        await this.open(session.id); // el servidor y el cliente se desincronizaron
        return;
      }
      if (isUncertainOutcome(error)) {
        // Nunca se reenvía sola: primero se pregunta al servidor qué guardó.
        await this.confirmAnswer(session, question, option);
        return;
      }
      this.fail(error);
    } finally {
      this.busy = false;
    }
  }

  /**
   * Resincroniza con GET /sessions/{id}/attempts tras perder la respuesta de un envío.
   * El plazo de la pregunta no se toca: lo gobierna el servidor.
   */
  private async confirmAnswer(
    session: Session,
    question: Question,
    option: OptionLabel | null,
  ): Promise<void> {
    this.uncertain = { session, question, option, missing: false };
    let attempts: Attempt[];
    try {
      attempts = await this.api.attempts(session.id);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 404)) {
        this.fail(error);
        return;
      }
      // No pudimos comprobarlo: no es lo mismo que "no se guardó".
      this.emit({ kind: "unconfirmed", session, question, option, saved: "unknown" });
      return;
    }
    const saved = attempts.find((a) => a.position === question.position);
    if (saved) {
      this.uncertain = null;
      this.answered = attempts.length;
      this.question = null;
      this.emit({
        kind: "result",
        session,
        question,
        attempt: saved,
        isLast: this.answered >= session.question_count,
      });
      return;
    }
    this.uncertain.missing = true;
    this.emit({ kind: "unconfirmed", session, question, option, saved: "missing" });
  }

  /** Vuelve a preguntar al servidor si guardó la respuesta (no reenvía nada). */
  async checkAnswer(): Promise<void> {
    const u = this.uncertain;
    if (!u || this.busy) return;
    this.busy = true;
    try {
      await this.confirmAnswer(u.session, u.question, u.option);
    } finally {
      this.busy = false;
    }
  }

  /**
   * Reenvío manual de la MISMA posición y opción, solo tras confirmar que no se guardó.
   * El servidor decide con su reloj: si el plazo ya venció, queda como sin respuesta.
   */
  async resendAnswer(): Promise<void> {
    const u = this.uncertain;
    if (!u || !u.missing || this.busy) return;
    await this.submit(u.option);
  }

  /** Pasa a la siguiente pregunta (o al resumen si ya no quedan). */
  async continue(): Promise<void> {
    if (!this.session) return;
    try {
      await this.loadQuestion();
    } catch (error) {
      this.fail(error);
    }
  }

  async abandon(): Promise<void> {
    if (!this.session) return;
    try {
      this.session = await this.api.abandon(this.session.id);
      await this.showSummary();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await this.showSummary(); // ya estaba completada
        return;
      }
      this.fail(error);
    }
  }

  private async loadQuestion(): Promise<void> {
    const session = this.session!;
    try {
      const question = await this.api.nextQuestion(session.id);
      this.question = question;
      this.emit({
        kind: "question",
        session,
        question,
        offsetMs: clockOffset(Date.parse(question.server_now), this.now()),
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // Sesión cerrada o sin preguntas pendientes: lo que queda es el resumen.
        await this.showSummary();
        return;
      }
      throw error;
    }
  }

  private async showSummary(): Promise<void> {
    const sessionId = this.session!.id;
    const [session, attempts] = await Promise.all([
      this.api.getSession(sessionId),
      this.api.attempts(sessionId),
    ]);
    this.session = session;
    this.emit({ kind: "summary", session, attempts });
  }

  private fail(error: unknown): void {
    const { reason, message } = describeFailure(error);
    this.emit({ kind: "error", reason, message });
  }
}
