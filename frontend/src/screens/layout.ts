import { h, type Child } from "../dom";
import { hrefFor } from "../router";
import type { Deps } from "../deps";

/** Barra superior con navegación y cierre de sesión. */
export function navBar(deps: Deps, active: "home" | "ranking" | "none"): HTMLElement {
  return h(
    "header",
    { class: "topbar" },
    h("span", { class: "brand" }, "CANE Prep"),
    h(
      "nav",
      { "aria-label": "Principal" },
      h("a", { href: hrefFor({ name: "home" }), "aria-current": active === "home" ? "page" : undefined }, "Inicio"),
      h("a", { href: hrefFor({ name: "ranking" }), "aria-current": active === "ranking" ? "page" : undefined }, "Ranking"),
      h("button", { type: "button", class: "link", onclick: () => void deps.signOut() }, "Cerrar sesión"),
    ),
  );
}

export function card(...children: Child[]): HTMLElement {
  return h("section", { class: "card" }, ...children);
}

export function errorNotice(message: string): HTMLElement {
  return h("p", { class: "notice error", role: "alert" }, message);
}

export function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}
