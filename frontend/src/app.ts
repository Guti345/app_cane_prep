import type { ApiClient } from "./api";
import type { Deps } from "./deps";
import { currentRoute, navigate, onRouteChange, type Route } from "./router";
import { renderHome } from "./screens/home";
import { renderLogin } from "./screens/login";
import { renderPlayScreen } from "./screens/playScreen";
import { renderRanking } from "./screens/ranking";
import type { PendingCreateStore } from "./pendingCreate";
import type { ActiveSessionStore } from "./store";
import type { AuthService } from "./supabase";

export interface Services {
  auth: AuthService;
  api: ApiClient;
  store: ActiveSessionStore;
  pendingCreate: PendingCreateStore;
  apiUrl: string;
}

/**
 * Monta la aplicación. Cada cambio de ruta limpia la pantalla anterior
 * (cronómetros incluidos) y exige sesión salvo en el login.
 */
export async function mountApp(root: HTMLElement, services: Services): Promise<void> {
  let cleanup: () => void = () => {};
  let renderId = 0;
  let loginNotice: string | undefined;

  const deps: Deps = {
    ...services,
    go: navigate,
    async signOut(notice) {
      await services.auth.signOut();
      services.store.clear();
      loginNotice = notice;
      navigate({ name: "login" });
    },
  };

  async function render(route: Route): Promise<void> {
    const id = ++renderId;
    cleanup();
    cleanup = () => {};

    const signedIn = (await services.auth.getAccessToken()) !== null;
    if (id !== renderId) return; // llegó una ruta más reciente

    if (!signedIn && route.name !== "login") {
      navigate({ name: "login" });
      return;
    }
    if (signedIn && (route.name === "login" || route.name === "notfound")) {
      navigate({ name: "home" });
      return;
    }

    switch (route.name) {
      case "login": {
        const notice = loginNotice;
        loginNotice = undefined;
        cleanup = renderLogin(root, deps, notice);
        break;
      }
      case "home":
        await renderHome(root, deps);
        break;
      case "play":
        cleanup = renderPlayScreen(root, deps, route.sessionId);
        break;
      case "ranking":
        await renderRanking(root, deps);
        break;
    }
  }

  onRouteChange((route) => void render(route));
  services.auth.onSignedOut(() => navigate({ name: "login" }));
  await render(currentRoute());
}
