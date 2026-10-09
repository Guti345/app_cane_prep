import "./styles.css";
import { checkHealth, getApiUrl } from "./api";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) {
  throw new Error("No se encontró el contenedor #app.");
}

app.innerHTML = `
  <main class="shell">
    <h1>CANE Prep</h1>
    <p class="lead">Práctica de Microeconomía, Macroeconomía, Econometría e
      Historia y Pensamiento Económico.</p>

    <section class="card">
      <h2>Estado del proyecto</h2>
      <p>En construcción. Solo existe el arranque local: todavía no hay
        inicio de sesión, preguntas ni ranking.</p>
    </section>

    <section class="card">
      <h2>Backend</h2>
      <p class="muted">API configurada: <code id="api-url"></code></p>
      <button id="check-health" type="button">Consultar /health</button>
      <p id="health-status" class="status" role="status" aria-live="polite">
        Sin consultar.
      </p>
    </section>
  </main>
`;

const apiUrlEl = app.querySelector<HTMLElement>("#api-url");
const button = app.querySelector<HTMLButtonElement>("#check-health");
const statusEl = app.querySelector<HTMLElement>("#health-status");

if (!apiUrlEl || !button || !statusEl) {
  throw new Error("No se pudo montar la pantalla.");
}

apiUrlEl.textContent = getApiUrl() ?? "(sin configurar)";

function setStatus(kind: "idle" | "pending" | "ok" | "error", text: string) {
  statusEl!.dataset.state = kind;
  statusEl!.textContent = text;
}

button.addEventListener("click", async () => {
  button.disabled = true;
  setStatus("pending", "Consultando…");
  try {
    const result = await checkHealth();
    if (result.status === "ok") {
      setStatus("ok", "El backend respondió correctamente.");
    } else {
      setStatus("error", result.message);
    }
  } finally {
    button.disabled = false;
  }
});
