import { describe, expect, it } from "vitest";
import { readConfig } from "./config";

const FULL = {
  VITE_API_URL: "http://localhost:8000/",
  VITE_SUPABASE_URL: "https://proyecto-ficticio.supabase.co",
  VITE_SUPABASE_PUBLISHABLE_KEY: "clave-publicable-ficticia",
};

describe("readConfig", () => {
  it("lee las tres variables y quita la barra final", () => {
    const result = readConfig(FULL);

    expect(result).toEqual({
      ok: true,
      config: {
        apiUrl: "http://localhost:8000",
        supabaseUrl: "https://proyecto-ficticio.supabase.co",
        supabasePublishableKey: "clave-publicable-ficticia",
      },
    });
  });

  it("informa qué variables faltan, sin lanzar", () => {
    const result = readConfig({ VITE_API_URL: "http://localhost:8000" });

    expect(result).toEqual({
      ok: false,
      missing: ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"],
    });
  });

  it("trata valores vacíos o con espacios como ausentes", () => {
    const result = readConfig({ ...FULL, VITE_SUPABASE_PUBLISHABLE_KEY: "   " });

    expect(result).toEqual({ ok: false, missing: ["VITE_SUPABASE_PUBLISHABLE_KEY"] });
  });
});
