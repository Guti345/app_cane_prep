import { h, type Child } from "../dom";
import { hrefFor } from "../router";
import type { Deps } from "../deps";
import { AREA_LABELS, type Area } from "../types";
import logoUrl from "../../logo_cane.png";

/**
 * Logo del CANE. El archivo se usa tal cual (2172 x 724, proporción 3:1): solo se fija la
 * altura y el ancho queda en automático. El nombre accesible es "CANE Prep".
 */
export function brandLogo(size: "header" | "login" = "header"): HTMLImageElement {
  return h("img", {
    class: `brand-logo ${size}`,
    src: logoUrl,
    alt: "CANE Prep",
    width: 2172,
    height: 724,
  });
}

/** Barra superior con navegación y cierre de sesión. */
export function navBar(deps: Deps, active: "home" | "ranking" | "none"): HTMLElement {
  return h(
    "header",
    { class: "topbar" },
    h("span", { class: "brand" }, brandLogo("header")),
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

/** "Microeconomía 57": área + número de la pregunta en el banco fuente (PDF). */
export function sourceReference(item: { area: Area; source_number: number }): string {
  return `${AREA_LABELS[item.area]} ${item.source_number}`;
}

/**
 * Contenedor con desplazamiento horizontal para una tabla ancha. Es una región con
 * nombre y enfocable, para que también se pueda recorrer con teclado.
 */
export function scrollRegion(label: string, content: Node): HTMLElement {
  return h("div", { class: "table-scroll", role: "region", tabindex: 0, "aria-label": label }, content);
}

export function errorNotice(message: string): HTMLElement {
  return h("p", { class: "notice error", role: "alert" }, message);
}

export function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
}
