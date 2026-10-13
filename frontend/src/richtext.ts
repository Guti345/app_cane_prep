/**
 * Texto enriquecido de preguntas: Markdown (negrita, cursiva, listas, tablas,
 * saltos de línea), LaTeX y figuras.
 *
 * Seguridad, en capas:
 * 1. markdown-it con HTML desactivado: cualquier `<...>` del texto se escapa.
 * 2. Sin enlaces, sin bloques de código y sin imágenes que no estén en
 *    `assets` de la pregunta (se descartan): el texto no puede introducir una
 *    URL, ni propia ni ajena.
 * 3. KaTeX con `trust: false` y `throwOnError: false`; un error de LaTeX se
 *    muestra como texto, no rompe la pantalla.
 * 4. DOMPurify con lista blanca de etiquetas y atributos; devuelve un
 *    fragmento de DOM, así que nunca se usa `innerHTML`.
 * 5. Las imágenes salen sin `src`; solo `hydrateFigures` les pone un blob
 *    obtenido por el endpoint autenticado de la API.
 */

import DOMPurify from "dompurify";
import katex from "katex";
import MarkdownIt from "markdown-it";
import type { MarkdownIt as MarkdownItInstance, StateInline } from "markdown-it";

/** Debe coincidir con el patrón de `question_assets.ref` y de la API. */
const FIGURE_REF = /^assets\/[a-z0-9_-]+\.(png|jpg|webp)$/;

export interface FigureInfo {
  ref: string;
  alt: string;
}

/** Figuras utilizables de una pregunta: ref válida y recurso disponible. */
export function figuresOf(assets: readonly Record<string, unknown>[]): FigureInfo[] {
  const figures: FigureInfo[] = [];
  for (const asset of assets) {
    const { ref, alt, status } = asset;
    if (typeof ref !== "string" || !FIGURE_REF.test(ref)) continue;
    if (status !== "available") continue;
    figures.push({ ref, alt: typeof alt === "string" ? alt : "" });
  }
  return figures;
}

// --- matemáticas ---------------------------------------------------------------------------

const DOLLAR = 0x24;
const BACKSLASH = 0x5c;

function isSpace(code: number): boolean {
  return code === 0x20 || code === 0x09 || code === 0x0a || code === 0x0d;
}

function isDigit(code: number): boolean {
  return code >= 0x30 && code <= 0x39;
}

/** `$...$` (en línea) y `$$...$$` (destacada). Un `$` suelto, como en "$5", queda como texto. */
function mathRule(state: StateInline, silent: boolean): boolean {
  const src = state.src;
  const start = state.pos;
  if (src.charCodeAt(start) !== DOLLAR) return false;

  const display = src.charCodeAt(start + 1) === DOLLAR;
  const opening = display ? 2 : 1;
  const contentStart = start + opening;
  if (contentStart >= state.posMax) return false;
  // En línea, el `$` de apertura no va seguido de espacio ("$ 5 y $ 6").
  if (!display && isSpace(src.charCodeAt(contentStart))) return false;

  let end = contentStart;
  for (;;) {
    end = src.indexOf("$", end);
    if (end === -1 || end >= state.posMax) return false;
    // Un `$` precedido por un número impar de barras está escapado.
    let slashes = 0;
    while (src.charCodeAt(end - 1 - slashes) === BACKSLASH) slashes += 1;
    if (slashes % 2 === 1) {
      end += 1;
      continue;
    }
    if (display) {
      if (src.charCodeAt(end + 1) === DOLLAR && end > contentStart) break;
      end += 1;
      continue;
    }
    const next = src.charCodeAt(end + 1);
    // El `$` de cierre no sigue a un espacio ni precede a un dígito ("$x$5").
    if (end === contentStart || isSpace(src.charCodeAt(end - 1)) || isDigit(next) || next === DOLLAR) {
      end += next === DOLLAR ? 2 : 1;
      continue;
    }
    break;
  }

  if (!silent) {
    const token = state.push(display ? "math_display" : "math_inline", "math", 0);
    token.content = src.slice(contentStart, end);
    token.markup = display ? "$$" : "$";
  }
  state.pos = end + opening;
  return true;
}

function renderMath(tex: string, displayMode: boolean, escape: (s: string) => string): string {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      trust: false,
      strict: "ignore",
      output: "htmlAndMathml",
      maxExpand: 1000,
      maxSize: 50,
    });
  } catch {
    // KaTeX con throwOnError:false casi no lanza; si lo hace, se muestra el texto.
    return `<code class="math-fallback">${escape(tex)}</code>`;
  }
}

// --- Markdown -----------------------------------------------------------------------------

/** Entorno de una llamada a markdown-it; `figures` asocia ref -> texto alternativo. */
type RenderEnv = Record<PropertyKey, unknown> & { figures: Map<string, string> };

function createMarkdown(): MarkdownItInstance {
  const md = new MarkdownIt("default", { html: false, linkify: false, breaks: true, typographer: false });
  // Sin enlaces ni bloques de código accidentales (una línea con sangría no es código).
  md.disable(["link", "autolink", "reference", "heading", "lheading", "code", "fence", "blockquote"]);
  md.inline.ruler.before("escape", "math", mathRule);

  const escape = md.utils.escapeHtml;
  md.renderer.rules["math_inline"] = (tokens, idx) => renderMath(tokens[idx]!.content, false, escape);
  md.renderer.rules["math_display"] = (tokens, idx) => renderMath(tokens[idx]!.content, true, escape);

  // Una imagen solo existe si su ruta está en los recursos de la pregunta; sale
  // sin `src` (la carga `hydrateFigures`). Cualquier otra se descarta.
  md.renderer.rules.image = (tokens, idx, _options, env) => {
    const token = tokens[idx]!;
    const ref = String(token.attrGet("src") ?? "");
    const declaredAlt = (env as RenderEnv | undefined)?.figures.get(ref);
    if (declaredAlt === undefined) return "";
    const alt = declaredAlt || token.content;
    return `<img class="figure" data-figure="${escape(ref)}" alt="${escape(alt)}">`;
  };
  return md;
}

const markdown = createMarkdown();

// --- sanitizado -----------------------------------------------------------------------------

const HTML_TAGS = [
  "p", "br", "strong", "em", "b", "i", "sub", "sup", "ul", "ol", "li", "table", "thead", "tbody",
  "tr", "th", "td", "code", "s", "span", "div", "img",
];
// Las que emite KaTeX (HTML + MathML + los SVG de delimitadores y raíces).
const MATH_TAGS = [
  "math", "semantics", "annotation", "mrow", "mi", "mn", "mo", "mtext", "mspace", "msup", "msub",
  "msubsup", "mfrac", "msqrt", "mroot", "mover", "munder", "munderover", "mtable", "mtr", "mtd",
  "mstyle", "mpadded", "mphantom", "menclose", "svg", "path", "line", "g",
];
const ATTRIBUTES = [
  "class", "style", "aria-hidden", "title", "alt", "data-figure", "colspan", "rowspan", "align",
  // KaTeX: MathML y SVG
  "xmlns", "encoding", "mathvariant", "stretchy", "fence", "separator", "lspace", "rspace",
  "minsize", "maxsize", "displaystyle", "scriptlevel", "columnalign", "columnspacing",
  "rowspacing", "columnlines", "rowlines", "linethickness", "width", "height", "depth",
  "voffset", "mathsize", "mathcolor", "mathbackground", "display", "notation", "movablelimits", "accent", "accentunder",
  "viewBox", "preserveAspectRatio", "d", "x1", "x2", "y1", "y2", "stroke", "stroke-width",
];

// El estilo en línea lo genera KaTeX; aun así, nada que cargue recursos o ejecute.
const RISKY_STYLE = /url\s*\(|expression\s*\(|@import|javascript:|behavior\s*:/i;

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node instanceof Element && node.hasAttribute("style")) {
    if (RISKY_STYLE.test(node.getAttribute("style") ?? "")) node.removeAttribute("style");
  }
});

/** Lista blanca de etiquetas y atributos. Exportada para probarla directamente. */
export function sanitizeHtml(html: string): DocumentFragment {
  const clean: Node | string = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...HTML_TAGS, ...MATH_TAGS],
    ALLOWED_ATTR: ATTRIBUTES,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    // Ambas: siempre un fragmento. Con solo RETURN_DOM_FRAGMENT, DOMPurify devuelve
    // la cadena tal cual cuando el texto no contiene "<".
    RETURN_DOM: true,
    RETURN_DOM_FRAGMENT: true,
  });
  if (clean instanceof DocumentFragment) return clean;
  // No debería ocurrir; si ocurre, lo que llegue se trata como texto (nunca como HTML).
  const fragment = document.createDocumentFragment();
  fragment.append(typeof clean === "string" ? clean : (clean.textContent ?? ""));
  return fragment;
}

// --- API --------------------------------------------------------------------------------------

export interface RichOptions {
  /** Recursos de la pregunta (`question.assets`); solo estas imágenes se dibujan. */
  assets?: readonly Record<string, unknown>[];
}

function envFor(options: RichOptions): RenderEnv {
  return { figures: new Map(figuresOf(options.assets ?? []).map((f) => [f.ref, f.alt])) };
}

/** Enunciado: bloques (párrafos, listas, tablas). */
export function renderRich(source: string, options: RichOptions = {}): DocumentFragment {
  return sanitizeHtml(markdown.render(source, envFor(options)).trim());
}

/** Texto de una opción: sin párrafos (cabe dentro de un botón). Sin imágenes. */
export function renderRichInline(source: string): DocumentFragment {
  return sanitizeHtml(markdown.renderInline(source, envFor({})).trim());
}

/** Pide la imagen de `ref` y devuelve una URL local (blob:). */
export type FigureLoader = (ref: string) => Promise<string>;

/** Completa las imágenes de `root`. Si una falla, queda su texto alternativo. */
export function hydrateFigures(root: ParentNode, load: FigureLoader): void {
  for (const img of Array.from(root.querySelectorAll<HTMLImageElement>("img[data-figure]"))) {
    const ref = img.getAttribute("data-figure") ?? "";
    img.classList.add("loading");
    const missing = (): void => {
      const note = document.createElement("span");
      note.className = "figure-missing";
      note.textContent = `[Figura no disponible${img.alt ? `: ${img.alt}` : ""}]`;
      img.replaceWith(note);
    };
    if (!FIGURE_REF.test(ref)) {
      missing();
      continue;
    }
    load(ref).then(
      (url) => {
        img.classList.remove("loading");
        img.src = url;
      },
      missing,
    );
  }
}
