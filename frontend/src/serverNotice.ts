/**
 * Aviso de espera del servidor.
 *
 * Una única región `role="status"` / `aria-live="polite"`, creada antes de que haya
 * texto (las regiones vivas solo anuncian cambios en regiones ya presentes). El texto
 * se escribe UNA vez cuando la espera se alarga y se borra al terminar: no hay contador
 * por segundo, así que un lector de pantalla lo anuncia una sola vez por espera.
 */
import { h } from "./dom";

export const WAKING_MESSAGE =
  "Despertando el servidor. Puede tardar hasta un minuto; no hace falta que hagas nada.";

export interface ServerNotice {
  element: HTMLElement;
  onWaiting(waiting: boolean): void;
}

/** Inserta la región justo antes del contenedor de la aplicación. */
export function createServerNotice(appRoot: HTMLElement): ServerNotice {
  const element = h("div", {
    class: "server-status",
    role: "status",
    "aria-live": "polite",
    "aria-atomic": "true",
  });
  appRoot.parentElement?.insertBefore(element, appRoot);
  return {
    element,
    onWaiting(waiting) {
      element.textContent = waiting ? WAKING_MESSAGE : "";
    },
  };
}
