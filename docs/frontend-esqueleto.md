# Frontend: diseño e implementación

**Estado: implementado; probado en local y en un navegador real contra
`pruebas_cane`** (2026-10-12, resultado informado por el usuario: inicio de
sesión, sesión con cronómetro, recarga a mitad, ranking y CORS). Cubre las
fases 1 a 3. El 2026-10-13 se añadió el **texto enriquecido** (Markdown, LaTeX y
figuras; ver abajo), probado con el banco real y a 390 px de ancho. Lo que no
está hecho: pruebas con lector de pantalla y en un teléfono real, y despliegue
en Netlify.

Los cambios al backend B1, B2 y B3 se implementaron (ver
[`arquitectura.md`](arquitectura.md)).

## Restricciones

- Vite + TypeScript, **sin framework** (decisión de la parte 1).
- Solo tres variables públicas, ya definidas en `frontend/.env.example`:
  `VITE_API_URL`, `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`.
- Supabase **solo para Auth**. El navegador nunca lee tablas ni calcula
  aciertos; el contenido del juego pasa por FastAPI.
- Sin redirects de Netlify: rutas con `#` (hash).
- La clave publicable no da acceso a datos; la autorización la hace el backend.

## Dependencias nuevas

| Paquete | Para qué | Cuándo |
| --- | --- | --- |
| `@supabase/supabase-js` | Iniciar sesión, mantener y renovar el token | Fase 1 |
| `vitest` (dev) | Probar el cronómetro y la máquina de estados | Fase 1 |
| `markdown-it`, `katex`, `dompurify` | Enunciados con Markdown y LaTeX, con sanitizado | Fase 3 ✔ |
| `jsdom` (dev) | DOM completo para probar el sanitizado (con happy-dom, DOMPurify no filtra) | Fase 3 ✔ |

## Estructura

```
frontend/src/
  main.ts            arranque: lee config, monta el router
  config.ts          lee las 3 variables VITE_*; falla con aviso claro si faltan
  supabase.ts        cliente de Supabase, solo `auth` (nunca `.from()`/`.rpc()`)
  api.ts             cliente tipado de FastAPI (ya existe `checkHealth`)
  types.ts           tipos que reflejan los esquemas de la API
  router.ts          router por hash: #/login, #/, #/jugar/:id, #/ranking
  store.ts           estado en memoria + sesión activa en localStorage
  timer.ts           cuenta atrás basada en el plazo del servidor (sin DOM)
  dom.ts             ayudantes para construir nodos con textContent
  screens/
    login.ts  home.ts  question.ts  result.ts  summary.ts  ranking.ts
  styles.css
```

Una pantalla = un módulo con `render(container, params)`; sin plantillas con
`innerHTML` para datos del servidor (ver Seguridad).

## Pantallas

| Ruta | Pantalla | Qué hace |
| --- | --- | --- |
| `#/login` | **Login** | Correo y contraseña con `signInWithPassword`. Sin registro ni "olvidé mi contraseña" en esta fase (acceso cerrado a cinco personas). |
| `#/` | **Inicio** | Elegir modo: por área, aleatorio o simulacro (fase 1, 2, semifinal, final). Si hay una sesión activa guardada, ofrece **Continuar**. Enlace a Ranking y a cerrar sesión. |
| `#/jugar/:id` | **Pregunta** | Enunciado, opciones y **cronómetro de 90 s**. Al elegir una opción se envía y pasa al resultado. |
| (misma ruta) | **Resultado** | Correcta/incorrecta, opción elegida y correcta, tiempo usado; botón **Siguiente**. Si venció: "Se acabó el tiempo". |
| (misma ruta) | **Resumen** | Al cerrar la sesión: aciertos, fallos, timeouts y tiempo promedio; enlace al ranking. |
| `#/ranking` | **Ranking** | Tabla del equipo. Quien tiene menos de 20 preguntas ve "faltan N" en lugar de puesto. |

Pregunta, Resultado y Resumen son estados de la misma ruta, no rutas: así
recargar siempre se resuelve preguntando al servidor.

## Flujo de una sesión

```
Inicio ── POST /sessions ──► sesión (id guardado en localStorage)
   │
   ▼
POST /sessions/{id}/next ──► Pregunta (deadline_at del servidor)
   │  elegir opción  /  llega a 0
   ▼
POST /sessions/{id}/answer ──► Resultado (acierto, clave, tiempo)
   │  Siguiente
   ▼
POST .../next ──► Pregunta N+1   …   409 "sin preguntas" ──► Resumen
```

Recarga en cualquier punto: `GET /sessions/{id}` y `POST .../next` devuelven la
pregunta pendiente **con el mismo plazo**; el cronómetro retoma donde estaba.

## Cronómetro de 90 s

- El servidor manda `deadline_at`. El cliente solo **muestra** el tiempo que
  falta; no decide nada. A 0 envía la respuesta (la opción marcada, o `null`) y
  el servidor resuelve si llegó a tiempo.
- Se calcula siempre como `deadline_at − ahora`, nunca restando segundos: así
  sobrevive a pestañas en segundo plano y a recargas.
- **Desfase de reloj.** Si el reloj del equipo está adelantado o atrasado, la
  cuenta mostrada sería falsa. Se corrige con la hora del servidor (ver cambio
  B1 abajo): `offset = server_now − Date.now()` al recibir cada pregunta.
- Accesibilidad: el contador visible es `aria-hidden`; una región `aria-live`
  anuncia solo a los 30, 10 y 5 s. Color y texto, no solo color.
- Al enviar se deshabilitan las opciones de inmediato (evita doble envío; el
  servidor además ignora el segundo).

## Cambios que pide al backend

Todos pequeños, pero **no existen hoy** y hay que decidirlos:

| Id | Cambio | Por qué |
| --- | --- | --- |
| B1 | Añadir `server_now` (hora del servidor) a la respuesta de `next` y de `GET /sessions/{id}` | Corregir el desfase de reloj del cronómetro |
| B2 | `GET /ranking`: filas de `practice_ranking` del equipo del usuario | Pantalla de ranking |
| B3 | `GET /sessions/{id}/attempts`: intentos ya cerrados con su clave | Resumen fiable tras recargar y para ver timeouts registrados por `next` |

Contrato propuesto para B2 y B3:

```ts
interface RankingRow {
  display_name: string;
  rank_position: number | null;   // null si tiene menos de 20 preguntas
  questions_seen: number;
  correct_count: number;
  accuracy_pct: number | null;
  avg_time_seconds: number | null;
  sessions_completed: number;
}
```

`B2` solo sirve filas del equipo del usuario verificado, nunca por parámetro.
`B3` solo devuelve posiciones ya respondidas, así que revela claves únicamente
de preguntas cerradas.

## Contrato con la API actual

```ts
type Mode = "area" | "random" | "simulacro";
type Area = "microeconomia" | "macroeconomia" | "econometria" | "historia_pensamiento";
type Stage = "fase_1" | "fase_2" | "semifinal" | "final";
type OptionLabel = "A" | "B" | "C" | "D" | "E";

interface Session { id: string; mode: Mode; area: Area | null; stage: Stage | null;
  question_count: number; status: "active" | "completed" | "abandoned";
  answered_count: number; current_position: number | null;
  current_deadline_at: string | null; }

interface Question { position: number; area: Area; statement_md: string;
  options: { label: OptionLabel; text_md: string }[];
  assets: Record<string, unknown>[]; deadline_at: string; }   // sin clave

interface Attempt { position: number; selected_option: OptionLabel | null;
  is_correct: boolean; timed_out: boolean; time_used_ms: number;
  correct_option: OptionLabel; }
```

Manejo de errores del cliente de API:

| Código | Qué hace la UI |
| --- | --- |
| 401 | Cierra sesión local y va a `#/login` ("Tu sesión venció"). |
| 403 | "Tu usuario no tiene equipo asignado. Avisa al administrador." |
| 404 | Olvida la sesión guardada y vuelve al inicio. |
| 409 | Según el contexto: sesión cerrada → Resumen; pregunta no emitida → recarga estado. |
| 422 | Error de programación o dato inválido: mensaje genérico y log en consola. |
| 503 / sin red | "No se pudo conectar" con **Reintentar**; no pierde el estado. |

## Seguridad

- **Supabase solo `auth`.** Un chequeo automático (script en `npm run
  typecheck` o prueba) falla si el código usa `.from(`, `.rpc(` o `.storage`.
- **Token.** Lo gestiona `supabase-js` (renovación automática); se pide con
  `getSession()` en cada llamada y no se copia a otras variables ni se
  registra en consola.
- **XSS.** `statement_md` y `text_md` vienen de la base y pasan por
  `src/richtext.ts` (ver "Texto enriquecido"): HTML desactivado en
  markdown-it, lista blanca de DOMPurify y un fragmento de DOM, sin `innerHTML`.
- **Nada de respuestas en el cliente.** La clave solo aparece en la respuesta de
  `answer` (y en B3 para posiciones cerradas). No se cachea ni se guarda.
- **localStorage** guarda solo el id de la sesión activa. No guarda token
  propio, preguntas ni resultados.
- El build no debe contener claves privadas ni cadenas de conexión (ya se
  verifica en la parte 2).

## Pruebas

| Qué | Cómo |
| --- | --- |
| Cronómetro | Vitest con reloj simulado: recarga, desfase, pestaña oculta, llega a 0. |
| Máquina de estados | Vitest: secuencia de respuestas de la API → pantalla esperada, incluidos 401/409/503. |
| Tipos y build | `npm run typecheck` y `npm run build` (ya existen). |
| Integración | El backend local (PostgreSQL + Auth falso) que ya se usa en las pruebas puede servir de base para un recorrido automatizado más adelante. |

## Fases

| Fase | Entrega | Depende de |
| --- | --- | --- |
| 1 | Config, Supabase Auth, cliente de API tipado, login y cierre de sesión, guardia de rutas | Nada nuevo |
| 2 | Inicio, crear sesión, pregunta con cronómetro, resultado, siguiente, recarga | B1 (sin B1: cronómetro con desfase posible, marcado) |
| 3 | Resumen y ranking; Markdown/LaTeX; recursos (imágenes) ✔ | B2, B3, figuras en la base |
| 4 | Pulido móvil, estados de carga y errores, pruebas de accesibilidad | — |

## Decisiones

Tomadas:

1. **B1, B2 y B3**: aprobadas e implementadas.
2. ~~Texto plano~~ **Sustituida (2026-10-12/13):** el banco real trae LaTeX
   (120 de las 427 activas), tablas (8) e imágenes (8). Markdown con KaTeX, HTML
   desactivado, sanitizado por lista blanca, figuras desde un endpoint
   autenticado y desplazamiento horizontal en fórmulas anchas (aprobado por
   Antonio).
3. **"Continuar sesión"** con el id guardado en el navegador (por dispositivo).
4. **Sin recuperación de contraseña**: la cambia el administrador desde el
   panel. La pantalla de login lo indica.

Abiertas:

1. ~~Formato de `assets`~~ **Cerrada:** `bytea` en PostgreSQL y endpoint
   autenticado de FastAPI (ver "Texto enriquecido").
2. Textos finales de la interfaz y pulido móvil (fase 4).
3. **Lector de pantalla y móvil**: el recorrido ya se probó en un navegador de
   escritorio real; falta probarlo con lector de pantalla y en un teléfono.
4. Si "Continuar" debe funcionar entre dispositivos, habría que añadir
   `GET /sessions?status=active`.

## Texto enriquecido

`src/richtext.ts`: `renderRich` (enunciado, bloques), `renderRichInline`
(opciones, caben en un botón) y `hydrateFigures`.

| Qué | Cómo |
| --- | --- |
| Markdown | `markdown-it` con `html: false`; sin enlaces, sin encabezados, sin bloques de código ni citas (una línea con sangría no es código). Negrita, cursiva, listas, tablas y saltos de línea. |
| LaTeX | Regla propia: `$...$` y `$$...$$`. Un `$` suelto ("$50.000") queda como texto y un `$` precedido de barra invertida es literal. KaTeX con `trust: false` y `throwOnError: false`: una fórmula inválida se ve en rojo, no rompe la pantalla. |
| Sanitizado | DOMPurify con lista blanca de etiquetas y atributos (HTML, MathML y los SVG que emite KaTeX); los estilos con `url()` o `expression` se eliminan. Devuelve un fragmento de DOM. |
| Figuras | Solo se dibuja `![alt](assets/x.png)` si `assets/x.png` está en los `assets` de la pregunta y su estado es `available`; cualquier otra imagen se descarta. La `img` sale sin `src`; `hydrateFigures` pide el archivo a `GET /sessions/{id}/questions/{n}/assets/{name}` con el token y le pone un `blob:`. Se liberan al cambiar de pantalla. |
| Móvil | Tablas y ecuaciones destacadas con `overflow-x: auto`; imágenes con `max-width: 100%`. |

**Prueba con el banco real (2026-10-13).** Las 483 preguntas pasaron por el
renderizador: 791 ecuaciones, 0 errores de KaTeX, 10 tablas, 14 de 14 figuras
dibujadas, ninguna imagen en opciones y ningún `$` visible que no fuera dinero.

**Prueba visual a 390 px** con el front y el backend reales sobre PostgreSQL
local (Edge sin interfaz, `iframe` de 390 px): econometría 15 (ecuación
destacada), 51 (tabla), 6 y 56 (figuras, una con dos gráficos), 18 (ecuación y
opciones) y microeconomía 105 (`<` y `>` dentro de fórmulas). Las figuras
cargaron por el endpoint autenticado. Con un `$$...$$` ancho el bloque se
desplaza horizontalmente, sin señal visual de que hay más. No se probó en un
teléfono real ni con lector de pantalla.

**Límite conocido.** KaTeX emite MathML mal formado para algunas expresiones
(p. ej. una flecha con una letra encima); DOMPurify descarta ese subárbol del
MathML. La versión visual queda intacta; solo se pierde esa parte para lectores
de pantalla.

## Notas de implementación

- El cronómetro calcula siempre `deadline_at − (ahora + desfase)`, con el
  desfase `server_now − Date.now()` medido al recibir cada pregunta. No
  descuenta la latencia de la red (puede mostrar menos de un segundo de más); el
  servidor es quien decide.
- Un vencimiento sin respuesta lo registra el servidor: el cliente envía
  `selected_option: null` al llegar a cero, y `next` también registra
  los timeouts de preguntas vencidas.
- Estructura real: `src/config.ts`, `supabase.ts`, `api.ts`, `play.ts`
  (máquina de estados sin DOM), `timer.ts`, `router.ts`, `store.ts`, `dom.ts`
  (construcción de nodos sin `innerHTML`) y `src/screens/`.
- El cliente valida la forma de cada respuesta; si el backend cambia, falla con
  un error claro en lugar de pintar datos a medias.
