/** Tipos que reflejan los esquemas de la API (backend/app/schemas.py). */

export type Mode = "area" | "random" | "simulacro";
export type Area =
  | "microeconomia"
  | "macroeconomia"
  | "econometria"
  | "historia_pensamiento";
export type Stage = "fase_1" | "fase_2" | "semifinal" | "final";
export type OptionLabel = "A" | "B" | "C" | "D" | "E";
export type SessionStatus = "active" | "completed" | "abandoned";

export interface Session {
  id: string;
  mode: Mode;
  area: Area | null;
  stage: Stage | null;
  question_count: number;
  status: SessionStatus;
  answered_count: number;
  current_position: number | null;
  current_deadline_at: string | null;
  server_now: string;
}

export interface QuestionOption {
  label: OptionLabel;
  text_md: string;
}

/** Pregunta emitida. No lleva la respuesta correcta. */
export interface Question {
  position: number;
  area: Area;
  statement_md: string;
  options: QuestionOption[];
  assets: Record<string, unknown>[];
  deadline_at: string;
  server_now: string;
}

export interface Attempt {
  position: number;
  selected_option: OptionLabel | null;
  is_correct: boolean;
  timed_out: boolean;
  time_used_ms: number;
  correct_option: OptionLabel;
}

export interface RankingRow {
  display_name: string;
  rank_position: number | null;
  questions_seen: number;
  correct_count: number;
  accuracy_pct: number | null;
  avg_time_seconds: number | null;
  sessions_completed: number;
  is_me: boolean;
}

export interface CreateSessionInput {
  mode: Mode;
  area?: Area;
  stage?: Stage;
  question_count?: number;
}

export interface AnswerInput {
  position: number;
  selected_option: OptionLabel | null;
}

/** Mínimo de preguntas distintas para aparecer en el ranking (decisión del equipo). */
export const MIN_QUESTIONS_FOR_RANKING = 20;

/** Plazo por pregunta. Es informativo: el servidor impone el plazo real. */
export const QUESTION_SECONDS = 90;

export const AREA_LABELS: Record<Area, string> = {
  microeconomia: "Microeconomía",
  macroeconomia: "Macroeconomía",
  econometria: "Econometría",
  historia_pensamiento: "Historia y Pensamiento Económico",
};

export const STAGE_LABELS: Record<Stage, string> = {
  fase_1: "Fase 1 (16 preguntas)",
  fase_2: "Fase 2 (12 preguntas)",
  semifinal: "Semifinal (8 preguntas)",
  final: "Final (4 preguntas)",
};
