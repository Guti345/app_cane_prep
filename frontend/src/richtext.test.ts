// @vitest-environment jsdom
// jsdom y no happy-dom: DOMPurify solo está soportado con un DOM completo (con happy-dom
// no quita atributos como onclick y la prueba de sanitizado no probaría nada).
import katex from "katex";
import { describe, expect, it, vi } from "vitest";
import {
  figuresOf,
  hydrateFigures,
  renderRich,
  renderRichInline,
  sanitizeHtml,
} from "./richtext";

const FIGURE = {
  ref: "assets/cane-2026-econometria-006-fig-01.png",
  kind: "figure",
  alt: "Serie de la variación del tipo de cambio",
  source_page: 3,
  status: "available",
};

function html(fragment: DocumentFragment): string {
  const box = document.createElement("div");
  box.append(fragment);
  return box.innerHTML; // solo en pruebas: para inspeccionar el resultado
}

function box(fragment: DocumentFragment): HTMLElement {
  const el = document.createElement("div");
  el.append(fragment);
  return el;
}

describe("Markdown", () => {
  it("dibuja párrafos, negrita, cursiva y saltos de línea", () => {
    const el = box(renderRich("Primera **fuerte** y *suave*.\nSegunda línea.\n\nOtro párrafo."));

    expect(el.querySelectorAll("p")).toHaveLength(2);
    expect(el.querySelector("strong")?.textContent).toBe("fuerte");
    expect(el.querySelector("em")?.textContent).toBe("suave");
    expect(el.querySelectorAll("br")).toHaveLength(1);
  });

  it("dibuja tablas con sus celdas", () => {
    const el = box(renderRich("| Variable | Coeficiente |\n|---|---|\n| ED | 0.078 |\n| EXPE | 0.035 |"));

    expect(el.querySelectorAll("th")).toHaveLength(2);
    expect(el.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(el.querySelector("tbody td")?.textContent).toBe("ED");
  });

  it("las opciones se dibujan sin párrafos (caben en un botón)", () => {
    const el = box(renderRichInline("El $R^2$ es **alto**"));

    expect(el.querySelector("p")).toBeNull();
    expect(el.querySelector(".katex")).not.toBeNull();
    expect(el.querySelector("strong")?.textContent).toBe("alto");
  });
});

describe("el texto no puede introducir HTML, enlaces ni URLs", () => {
  it("el HTML del enunciado se muestra como texto", () => {
    const source = '<script>alert(1)</script> <img src=x onerror="alert(2)"> <b onclick="x()">negrita</b>';
    const el = box(renderRich(source));

    expect(el.querySelector("script")).toBeNull();
    expect(el.querySelector("img")).toBeNull();
    expect(el.querySelector("b")).toBeNull();
    expect(el.textContent).toContain("<script>alert(1)</script>");
  });

  it("los enlaces Markdown no son enlaces", () => {
    const el = box(renderRich("[pulse](javascript:alert(1)) y [web](https://evil.test) y <https://evil.test>"));

    expect(el.querySelector("a")).toBeNull();
    expect(el.textContent).toContain("pulse");
  });

  it("una imagen que no está en los recursos de la pregunta se descarta", () => {
    const source = [
      "![ajena](https://evil.test/pixel.png)",
      "![otra](assets/cane-2026-macroeconomia-001-fig-01.png)",
      "![data](data:image/png;base64,AAAA)",
      "![js](javascript:alert(1))",
      "texto que se conserva",
    ].join("\n\n");
    const el = box(renderRich(source, { assets: [FIGURE] }));

    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toContain("texto que se conserva");
    expect(html(renderRich(source, { assets: [FIGURE] }))).not.toMatch(/evil\.test|src=/);
  });

  it("una imagen listada sale sin src, con el texto alternativo declarado", () => {
    const el = box(renderRich(`![lo que diga el texto](${FIGURE.ref})`, { assets: [FIGURE] }));
    const img = el.querySelector("img");

    expect(img).not.toBeNull();
    expect(img?.hasAttribute("src")).toBe(false);
    expect(img?.getAttribute("data-figure")).toBe(FIGURE.ref);
    expect(img?.getAttribute("alt")).toBe(FIGURE.alt);
  });

  it("un recurso pendiente o con ruta inválida no habilita la imagen", () => {
    const pending = { ...FIGURE, status: "pending_extract" };
    const weird = { ...FIGURE, ref: "../secreto.png" };

    expect(figuresOf([pending, weird, { ...FIGURE, ref: 3 }])).toEqual([]);
    for (const asset of [pending, weird]) {
      const el = box(renderRich(`![x](${asset.ref})`, { assets: [asset] }));
      expect(el.querySelector("img")).toBeNull();
    }
  });

  it("las opciones nunca dibujan imágenes", () => {
    expect(box(renderRichInline(`![x](${FIGURE.ref})`)).querySelector("img")).toBeNull();
  });
});

describe("LaTeX", () => {
  it("ecuaciones en línea y destacadas", () => {
    const el = box(renderRich("Sea $X_t=u_t+\\theta u_{t-1}$ y\n\n$$\\sum_{i=1}^{n} x_i^2 = \\frac{a}{b}$$"));

    expect(el.querySelectorAll(".katex")).toHaveLength(2);
    expect(el.querySelectorAll(".katex-display")).toHaveLength(1);
    expect(el.querySelector("math")).not.toBeNull(); // MathML para lectores de pantalla
    expect(el.querySelector(".katex-error")).toBeNull();
  });

  it("microeconomía 105: '<' y '>' dentro de las ecuaciones no son HTML", () => {
    const el = box(renderRich("Los precios cumplen $p<q_1^L$ y $q_2^C>p$ en el equilibrio."));

    expect(el.querySelectorAll(".katex")).toHaveLength(2);
    expect(el.querySelector(".katex-error")).toBeNull();
    // Nada se interpretó como etiqueta: solo hay párrafo, texto y KaTeX.
    expect(el.textContent).toContain("en el equilibrio.");
    expect(html(renderRich("$a<b$ y $c>d$"))).not.toMatch(/<b |<b>|<d/);
  });

  it("un error de LaTeX no rompe la pantalla ni el resto del texto", () => {
    const render = () => box(renderRich("Antes $\\frac{1}{$ y $\\comando_inexistente{x}$ después."));

    expect(render).not.toThrow();
    const el = render();
    expect(el.querySelectorAll(".katex-error").length).toBeGreaterThan(0);
    expect(el.textContent).toContain("Antes");
    expect(el.textContent).toContain("después.");
  });

  it("KaTeX corre sin confianza: no admite enlaces ni recursos", () => {
    const source = "$\\href{javascript:alert(1)}{x}$ $\\url{https://evil.test}$ $\\includegraphics{https://evil.test/x.png}$";
    const out = html(renderRich(source));

    expect(out).not.toMatch(/<a[\s>]|href=|<img|evil\.test\/x\.png"/);
  });

  it("un dólar suelto es texto, no una ecuación", () => {
    const el = box(renderRich("Cuesta $5 y luego $10 más; y un \\$ escapado."));

    expect(el.querySelector(".katex")).toBeNull();
    expect(el.textContent).toContain("$5 y luego $10");
    expect(el.textContent).toContain("un $ escapado");
  });

  it("no interpreta guiones bajos ni asteriscos dentro de la fórmula como Markdown", () => {
    const el = box(renderRich("$a_i * b_j + c_k$ y _cursiva_"));

    expect(el.querySelectorAll("em")).toHaveLength(1);
    expect(el.querySelector(".katex")).not.toBeNull();
  });
});

describe("lista blanca de sanitizado", () => {
  it("elimina scripts, manejadores, estilos peligrosos y etiquetas no listadas", () => {
    const dirty = [
      "<script>alert(1)</script>",
      '<p onclick="x()" style="background:url(https://evil.test/p.png)">p</p>',
      '<iframe src="https://evil.test"></iframe>',
      '<a href="javascript:alert(1)">a</a>',
      '<img src="https://evil.test/x.png" onerror="x()" data-figure="assets/a.png">',
      "<form><input name=x></form>",
      "<style>*{display:none}</style>",
      '<svg><script>alert(1)</script><foreignObject><p>x</p></foreignObject></svg>',
    ].join("");
    const out = html(sanitizeHtml(dirty));

    expect(out).not.toMatch(/<script|onclick|onerror|<iframe|<a[\s>]|<form|<input|<style|foreignObject|evil\.test|javascript:/i);
    expect(out).toContain('data-figure="assets/a.png"'); // el atributo listado sí se conserva
  });

  it("deja intacta la parte visual de la salida real de KaTeX", () => {
    // La parte visual (.katex-html) debe quedar idéntica. El MathML (para lectores
    // de pantalla) también, salvo subárboles que KaTeX emite mal formados (p. ej.
    // un <mover> dentro de <mo> en \overset{d}{	o}) y que DOMPurify descarta a propósito.
    const formulas = [
      "\\frac{\\hat{\\beta}_1-\\beta_1}{\\mathrm{se}(\\hat{\\beta}_1)}",
      "\\sqrt{\\sum_{i=1}^{n}(x_i-\\bar{x})^2}",
      "\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}",
      "\\left(\\frac{\\partial f}{\\partial x}\\right)^{2} \\geq \\int_0^\\infty e^{-x}\\,dx",
      "\\underbrace{x+y}_{z} \\overset{d}{\\to} N(0,\\sigma^2)",
      "\\text{si } x \\in \\mathbb{R},\\ \\Delta y_t = \\alpha + \\varepsilon_t",
    ];
    for (const tex of formulas) {
      for (const displayMode of [false, true]) {
        const raw = katex.renderToString(tex, {
          displayMode, throwOnError: false, trust: false, strict: "ignore", output: "htmlAndMathml",
        });
        const before = document.createElement("div");
        before.innerHTML = raw; // solo en pruebas
        const after = box(sanitizeHtml(raw));

        expect(before.querySelector(".katex-error")).toBeNull();
        const visual = (el: HTMLElement) => el.querySelector(".katex-html") as HTMLElement;
        expect(visual(after).querySelectorAll("*").length).toBe(visual(before).querySelectorAll("*").length);
        expect(visual(after).textContent).toBe(visual(before).textContent);
        expect(visual(after).innerHTML).toBe(visual(before).innerHTML);
        expect(after.querySelector("math")).not.toBeNull();
      }
    }
  });
});

describe("hydrateFigures", () => {
  function withFigure(): HTMLElement {
    return box(renderRich(`![x](${FIGURE.ref})`, { assets: [FIGURE] }));
  }

  it("pone el blob obtenido como src de la imagen", async () => {
    const el = withFigure();
    const load = vi.fn().mockResolvedValue("blob:http://localhost/abc");

    hydrateFigures(el, load);
    await vi.waitFor(() => expect(el.querySelector("img")?.getAttribute("src")).toBe("blob:http://localhost/abc"));

    expect(load).toHaveBeenCalledWith(FIGURE.ref);
  });

  it("si la carga falla, deja un aviso con el texto alternativo y sigue", async () => {
    const el = withFigure();

    hydrateFigures(el, () => Promise.reject(new Error("404")));
    await vi.waitFor(() => expect(el.querySelector(".figure-missing")).not.toBeNull());

    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toContain(FIGURE.alt);
  });

  it("no pide nada para una referencia que no cumple el patrón", () => {
    const el = document.createElement("div");
    el.append(document.createRange().createContextualFragment(
      '<img data-figure="https://evil.test/x.png"><img data-figure="assets/../x.png">'));
    const load = vi.fn();

    hydrateFigures(el, load);

    expect(load).not.toHaveBeenCalled();
    expect(el.querySelectorAll(".figure-missing")).toHaveLength(2);
  });
});
