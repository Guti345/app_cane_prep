export interface AppConfig {
  apiUrl: string;
  supabaseUrl: string;
  supabasePublishableKey: string;
}

export type ConfigResult =
  | { ok: true; config: AppConfig }
  | { ok: false; missing: string[] };

const VARIABLES = {
  apiUrl: "VITE_API_URL",
  supabaseUrl: "VITE_SUPABASE_URL",
  supabasePublishableKey: "VITE_SUPABASE_PUBLISHABLE_KEY",
} as const;

/**
 * Lee las tres variables públicas. Nunca lanza: si falta alguna, devuelve su
 * nombre para mostrar un aviso claro en lugar de una pantalla en blanco.
 */
export function readConfig(env: Record<string, string | undefined>): ConfigResult {
  const values: Partial<Record<keyof AppConfig, string>> = {};
  const missing: string[] = [];

  for (const [key, variable] of Object.entries(VARIABLES) as [keyof AppConfig, string][]) {
    const value = env[variable]?.trim();
    if (value) {
      values[key] = value;
    } else {
      missing.push(variable);
    }
  }
  if (missing.length > 0) {
    return { ok: false, missing };
  }
  return {
    ok: true,
    config: {
      apiUrl: values.apiUrl!.replace(/\/+$/, ""),
      supabaseUrl: values.supabaseUrl!.replace(/\/+$/, ""),
      supabasePublishableKey: values.supabasePublishableKey!,
    },
  };
}
