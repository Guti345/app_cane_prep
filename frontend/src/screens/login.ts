import { checkHealth } from "../api";
import type { Deps } from "../deps";
import { h } from "../dom";
import { brandLogo, card } from "./layout";

/** Pantalla de acceso. Sin registro: las cuentas las crea el administrador. */
export function renderLogin(container: HTMLElement, deps: Deps, notice?: string): () => void {
  const status = h("p", { class: "notice", role: "status", "aria-live": "polite" });
  const email = h("input", {
    id: "email", name: "email", type: "email", autocomplete: "username",
    required: true, inputmode: "email",
  });
  const password = h("input", {
    id: "password", name: "password", type: "password",
    autocomplete: "current-password", required: true,
  });
  const submit = h("button", { type: "submit", class: "primary" }, "Entrar");
  const error = h("p", { class: "notice error", role: "alert", hidden: true });

  const form = h(
    "form",
    {
      novalidate: true,
      onsubmit: (event: Event) => {
        event.preventDefault();
        void doSignIn();
      },
    },
    h("label", { for: "email" }, "Correo"),
    email,
    h("label", { for: "password" }, "Contraseña"),
    password,
    error,
    submit,
  );

  async function doSignIn(): Promise<void> {
    error.hidden = true;
    if (!email.value.trim() || !password.value) {
      error.textContent = "Escribe tu correo y tu contraseña.";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    submit.textContent = "Entrando…";
    const result = await deps.auth.signIn(email.value.trim(), password.value);
    password.value = "";
    if (result.ok) {
      deps.go({ name: "home" });
      return;
    }
    error.textContent = result.message;
    error.hidden = false;
    submit.disabled = false;
    submit.textContent = "Entrar";
  }

  const healthButton = h(
    "button",
    {
      type: "button",
      class: "link",
      onclick: async () => {
        status.textContent = "Comprobando…";
        const result = await checkHealth(deps.apiUrl);
        status.textContent = result.ok ? "El servidor responde correctamente." : result.message;
      },
    },
    "Comprobar conexión con el servidor",
  );

  container.replaceChildren(
    h(
      "main",
      { class: "shell narrow" },
      // El título es la marca: el logo, con el mismo nombre accesible "CANE Prep".
      h("h1", { class: "login-brand" }, brandLogo("login")),
      h("p", { class: "lead" }, "Práctica para el concurso. Inicia sesión con tu cuenta."),
      notice ? h("p", { class: "notice" }, notice) : null,
      card(form),
      h("p", { class: "muted small" }, "¿Olvidaste tu contraseña? Pídele al administrador que la cambie."),
      healthButton,
      status,
    ),
  );
  email.focus();
  return () => {};
}
