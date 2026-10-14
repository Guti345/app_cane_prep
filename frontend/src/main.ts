import "katex/dist/katex.min.css";
import "./styles.css";
import { mountApp } from "./app";
import { createApiClient } from "./api";
import { readConfig } from "./config";
import { h } from "./dom";
import { createPendingCreateStore } from "./pendingCreate";
import { currentRoute } from "./router";
import { createServerNotice } from "./serverNotice";
import { createActiveSessionStore } from "./store";
import { createAuthService } from "./supabase";

const root = document.querySelector<HTMLDivElement>("#app");
if (!root) {
  throw new Error("No se encontró el contenedor #app.");
}

const result = readConfig(import.meta.env);

if (!result.ok) {
  // Aviso claro en lugar de una pantalla en blanco.
  root.replaceChildren(
    h(
      "main",
      { class: "shell narrow" },
      h("h1", null, "CANE Prep"),
      h(
        "p",
        { class: "notice error", role: "alert" },
        "Falta configuración: ",
        result.missing.join(", "),
        ". Copia frontend/.env.example a frontend/.env y complétalo.",
      ),
    ),
  );
} else {
  const { config } = result;
  const auth = createAuthService(config.supabaseUrl, config.supabasePublishableKey);
  const notice = createServerNotice(root);
  const api = createApiClient(config.apiUrl, () => auth.getAccessToken(), undefined, {
    onWaiting: notice.onWaiting,
  });
  // Al abrir la app, salvo que se retome una pregunta cuyo plazo ya corre: ahí no se
  // antepone ninguna espera; la propia petición de recuperación despierta al servidor.
  if (currentRoute().name !== "play") void api.warmUp();
  void mountApp(root, {
    auth,
    api,
    store: createActiveSessionStore(),
    pendingCreate: createPendingCreateStore(),
    apiUrl: config.apiUrl,
  });
}
