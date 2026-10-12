import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  announcement,
  clockOffset,
  formatClock,
  remainingMs,
  secondsLeft,
  startCountdown,
} from "./timer";

describe("cálculo del tiempo restante", () => {
  it("resta ahora al plazo del servidor", () => {
    expect(remainingMs(100_000, 40_000, 0)).toBe(60_000);
  });

  it("nunca es negativo", () => {
    expect(remainingMs(100_000, 150_000, 0)).toBe(0);
  });

  it("corrige un reloj de cliente adelantado", () => {
    // El servidor dice que son las 10:00:00; el cliente cree que son las 10:00:30.
    const offset = clockOffset(10_000_000, 10_030_000);
    expect(offset).toBe(-30_000);
    // Plazo = servidor + 90 s. Sin corregir mostraría 60 s; corregido, 90 s.
    expect(remainingMs(10_090_000, 10_030_000, offset)).toBe(90_000);
  });

  it("corrige un reloj de cliente atrasado", () => {
    const offset = clockOffset(10_000_000, 9_970_000);
    expect(remainingMs(10_090_000, 9_970_000, offset)).toBe(90_000);
  });

  it("redondea hacia arriba los segundos mostrados", () => {
    expect(secondsLeft(89_001)).toBe(90);
    expect(secondsLeft(1)).toBe(1);
    expect(secondsLeft(0)).toBe(0);
  });
});

describe("formato y avisos", () => {
  it.each([
    [90, "1:30"],
    [65, "1:05"],
    [9, "0:09"],
    [0, "0:00"],
    [-3, "0:00"],
  ])("formatClock(%i) = %s", (seconds, text) => {
    expect(formatClock(seconds)).toBe(text);
  });

  it("anuncia solo a los 30, 10 y 5 segundos", () => {
    expect([90, 31, 30, 29, 10, 5, 4].map(announcement)).toEqual([
      null, null, "Quedan 30 segundos", null, "Quedan 10 segundos", "Quedan 5 segundos", null,
    ]);
  });
});

describe("startCountdown", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup(offsetMs = 0, deadlineInMs = 90_000) {
    let clock = 1_000_000;
    const ticks: number[] = [];
    const onExpire = vi.fn();
    const countdown = startCountdown({
      deadlineMs: clock + deadlineInMs,
      offsetMs,
      now: () => clock,
      onTick: (seconds) => ticks.push(seconds),
      onExpire,
    });
    const advance = (ms: number) => {
      clock += ms;
      vi.advanceTimersByTime(ms);
    };
    return { ticks, onExpire, countdown, advance };
  }

  it("muestra 90 s al empezar y baja con el tiempo", () => {
    const { ticks, advance } = setup();
    expect(ticks[0]).toBe(90);

    advance(30_000);

    expect(ticks.at(-1)).toBe(60);
  });

  it("expira una sola vez al llegar a cero", () => {
    const { onExpire, advance } = setup();

    advance(89_000);
    expect(onExpire).not.toHaveBeenCalled();
    advance(2_000);
    advance(5_000);

    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it("al recargar, retoma donde iba (no reinicia a 90 s)", () => {
    // La pregunta se emitió hace 40 s: quedan 50 s.
    const { ticks } = setup(0, 50_000);

    expect(ticks[0]).toBe(50);
  });

  it("si el plazo ya venció, expira de inmediato", () => {
    const { onExpire, ticks } = setup(0, 0);

    expect(ticks[0]).toBe(0);
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it("al detenerlo no vuelve a avisar", () => {
    const { onExpire, countdown, advance } = setup();

    countdown.stop();
    advance(120_000);

    expect(onExpire).not.toHaveBeenCalled();
  });

  it("usa la hora del servidor: un desfase no cambia lo que se muestra", () => {
    // Cliente 20 s adelantado: offset = -20 s. El plazo (hora del servidor) es
    // server_now + 90 s = (ahora_cliente - 20 s) + 90 s = ahora_cliente + 70 s.
    const { ticks } = setup(-20_000, 70_000);

    expect(ticks[0]).toBe(90);
  });
});
