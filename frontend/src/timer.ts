/**
 * Cuenta atrás basada en el plazo del servidor.
 *
 * El cliente solo MUESTRA el tiempo que falta; el servidor decide si una
 * respuesta llegó a tiempo. Siempre se calcula `deadline - ahora` (nunca
 * restando segundos), así sobrevive a pestañas en segundo plano y recargas.
 */

/** Segundos en los que se anuncia el tiempo restante a lectores de pantalla. */
export const ANNOUNCE_AT_SECONDS: readonly number[] = [30, 10, 5];

/** Diferencia entre el reloj del servidor y el del cliente (ms). */
export function clockOffset(serverNowMs: number, clientNowMs: number): number {
  return serverNowMs - clientNowMs;
}

export function remainingMs(deadlineMs: number, nowMs: number, offsetMs: number): number {
  return Math.max(0, deadlineMs - (nowMs + offsetMs));
}

export function secondsLeft(remaining: number): number {
  return Math.ceil(remaining / 1000);
}

export function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${String(safe % 60).padStart(2, "0")}`;
}

export function announcement(seconds: number): string | null {
  return ANNOUNCE_AT_SECONDS.includes(seconds) ? `Quedan ${seconds} segundos` : null;
}

export interface CountdownOptions {
  deadlineMs: number;
  offsetMs: number;
  onTick: (seconds: number, remaining: number) => void;
  onExpire: () => void;
  now?: () => number;
  intervalMs?: number;
}

export interface Countdown {
  stop(): void;
}

export function startCountdown(options: CountdownOptions): Countdown {
  const now = options.now ?? Date.now;
  let stopped = false;
  let handle: ReturnType<typeof setInterval> | undefined;

  const stop = () => {
    stopped = true;
    if (handle !== undefined) clearInterval(handle);
  };

  const tick = () => {
    if (stopped) return;
    const remaining = remainingMs(options.deadlineMs, now(), options.offsetMs);
    options.onTick(secondsLeft(remaining), remaining);
    if (remaining <= 0) {
      stop();
      options.onExpire(); // una sola vez
    }
  };

  tick();
  if (!stopped) {
    handle = setInterval(tick, options.intervalMs ?? 250);
  }
  return { stop };
}
