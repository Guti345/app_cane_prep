/**
 * Reglas de seguridad del código del cliente, verificadas sobre el fuente.
 * Si una falla, no es "un detalle de la prueba": revisa el cambio.
 */
import { describe, expect, it } from "vitest";

const files = import.meta.glob<string>("/src/**/*.ts", {
  query: "?raw",
  import: "default",
  eager: true,
});

const production = Object.entries(files).filter(
  ([path]) => !path.endsWith(".test.ts") && !path.includes("__fixtures__"),
);

function offenders(pattern: RegExp, allow: string[] = []): string[] {
  return production
    .filter(([path]) => !allow.some((a) => path.endsWith(a)))
    .filter(([, source]) => pattern.test(source))
    .map(([path]) => path);
}

describe("el cliente de Supabase solo se usa para autenticación", () => {
  it("encuentra los archivos de producción", () => {
    expect(production.length).toBeGreaterThan(8);
  });

  it("no consulta tablas, RPC ni almacenamiento", () => {
    expect(offenders(/\.from\(\s*["'`]/)).toEqual([]);
    expect(offenders(/\.rpc\(/)).toEqual([]);
    expect(offenders(/\.storage\b/)).toEqual([]);
    expect(offenders(/\.channel\(|\.realtime\b/)).toEqual([]);
  });

  it("importa @supabase/supabase-js únicamente en supabase.ts", () => {
    expect(offenders(/@supabase\/supabase-js/, ["/src/supabase.ts"])).toEqual([]);
  });
});

describe("no hay formas de ejecutar o inyectar HTML", () => {
  it.each([
    ["innerHTML", /\.innerHTML\b/],
    ["outerHTML", /\.outerHTML\b/],
    ["insertAdjacentHTML", /insertAdjacentHTML/],
    ["document.write", /document\.write\(/],
    ["eval", /\beval\(/],
    ["new Function", /new Function\(/],
    ["dangerouslySetInnerHTML", /dangerouslySetInnerHTML/],
  ])("sin %s", (_name, pattern) => {
    expect(offenders(pattern)).toEqual([]);
  });
});

describe("secretos y registros", () => {
  it("no hay claves privadas ni cadenas de conexión", () => {
    expect(offenders(/service_role|SECRET_KEY|DATABASE_URL|postgres(ql)?:\/\//i)).toEqual([]);
  });

  it("no se escribe en consola (evita filtrar tokens)", () => {
    expect(offenders(/console\.(log|debug|info|warn|error)\(/)).toEqual([]);
  });

  it("localStorage solo lo toca store.ts", () => {
    expect(offenders(/localStorage|sessionStorage/, ["/src/store.ts"])).toEqual([]);
  });

  it("solo se leen las tres variables públicas", () => {
    const used = new Set<string>();
    for (const [, source] of production) {
      for (const match of source.matchAll(/VITE_[A-Z_]+/g)) used.add(match[0]);
    }

    expect([...used].sort()).toEqual([
      "VITE_API_URL", "VITE_SUPABASE_PUBLISHABLE_KEY", "VITE_SUPABASE_URL",
    ]);
  });
});
