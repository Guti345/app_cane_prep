import type { ApiClient } from "./api";
import type { Route } from "./router";
import type { ActiveSessionStore } from "./store";
import type { AuthService } from "./supabase";

/** Lo que reciben las pantallas: servicios y navegación, nada más. */
export interface Deps {
  auth: AuthService;
  api: ApiClient;
  store: ActiveSessionStore;
  apiUrl: string;
  go(route: Route): void;
  /** Cierra la sesión y vuelve al login, con un aviso opcional. */
  signOut(notice?: string): Promise<void>;
}
