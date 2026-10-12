import { describe, expect, it } from "vitest";
import { createActiveSessionStore } from "./store";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

describe("ActiveSessionStore", () => {
  it("guarda, lee y borra el id de la sesión", () => {
    const store = createActiveSessionStore(memoryStorage());

    expect(store.get()).toBeNull();
    store.set("abc");
    expect(store.get()).toBe("abc");
    store.clear();
    expect(store.get()).toBeNull();
  });

  it("guarda únicamente el id, nada más", () => {
    const storage = memoryStorage();

    createActiveSessionStore(storage).set("abc");

    expect([...storage.data.values()]).toEqual(["abc"]);
  });

  it("funciona sin almacenamiento disponible", () => {
    const store = createActiveSessionStore(null);

    expect(() => store.set("x")).not.toThrow();
    expect(store.get()).toBeNull();
    expect(() => store.clear()).not.toThrow();
  });

  it("no se rompe si el almacenamiento lanza", () => {
    const hostile = {
      getItem: () => { throw new Error("bloqueado"); },
      setItem: () => { throw new Error("bloqueado"); },
      removeItem: () => { throw new Error("bloqueado"); },
    };
    const store = createActiveSessionStore(hostile);

    expect(store.get()).toBeNull();
    expect(() => store.set("x")).not.toThrow();
    expect(() => store.clear()).not.toThrow();
  });
});
