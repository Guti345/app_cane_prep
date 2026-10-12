// @vitest-environment node
/**
 * Recorrido completo del cliente contra un backend REAL.
 *
 * Se omite salvo que existan CANE_E2E_API_URL y CANE_E2E_TOKEN en el entorno
 * (el token es el de un usuario de PRUEBAS; no lo guardes en archivos).
 * Necesita un backend con al menos 3 preguntas activas.
 */
import { describe, expect, it } from "vitest";
import { createApiClient } from "./api";
import { PlayController, type PlayState } from "./play";

const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
const apiUrl = env.CANE_E2E_API_URL;
const token = env.CANE_E2E_TOKEN;

describe.skipIf(!apiUrl || !token)("recorrido contra un backend real", () => {
  const api = createApiClient(apiUrl ?? "", async () => token ?? null);

  it("sesión completa: pregunta, respuesta, resultado, resumen y ranking", async () => {
    const session = await api.createSession({ mode: "random", question_count: 3 });
    const states: PlayState[] = [];
    const controller = new PlayController(api, (s) => states.push(s));

    await controller.open(session.id);
    for (let position = 1; position <= 3; position += 1) {
      const state = states.at(-1)!;
      expect(state.kind).toBe("question");
      if (state.kind !== "question") return;
      expect(state.question.position).toBe(position);
      expect(JSON.stringify(state.question)).not.toContain("correct_option");
      // El plazo corregido con la hora del servidor queda en (0, 90] s.
      const remaining =
        Date.parse(state.question.deadline_at) - (Date.now() + state.offsetMs);
      expect(remaining).toBeGreaterThan(0);
      expect(remaining).toBeLessThanOrEqual(90_500);

      await controller.submit("A");
      const result = states.at(-1)!;
      expect(result.kind).toBe("result");
      if (result.kind === "result") {
        expect(result.attempt.correct_option).toMatch(/^[A-E]$/);
        expect(result.isLast).toBe(position === 3);
      }
      await controller.continue();
    }

    const summary = states.at(-1)!;
    expect(summary.kind).toBe("summary");
    if (summary.kind === "summary") {
      expect(summary.attempts).toHaveLength(3);
      expect(summary.session.status).toBe("completed");
    }

    const ranking = await api.ranking();
    expect(Array.isArray(ranking)).toBe(true);
  });

  it("recargar en mitad de una sesión devuelve la misma pregunta y plazo", async () => {
    const session = await api.createSession({ mode: "random", question_count: 2 });
    const first: PlayState[] = [];
    await new PlayController(api, (s) => first.push(s)).open(session.id);

    const reloaded: PlayState[] = [];
    await new PlayController(api, (s) => reloaded.push(s)).open(session.id);

    const a = first.at(-1)!;
    const b = reloaded.at(-1)!;
    expect(a.kind).toBe("question");
    expect(b.kind).toBe("question");
    if (a.kind === "question" && b.kind === "question") {
      expect(b.question.deadline_at).toBe(a.question.deadline_at);
      expect(b.question.position).toBe(a.question.position);
    }
    await api.abandon(session.id);
  });
});
