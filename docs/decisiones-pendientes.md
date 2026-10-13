# Decisiones

Lo cerrado y lo que sigue abierto. Una decisión "cerrada" está reflejada en la
migración y en el código, que aun así **no se han aplicado ni desplegado** en
el proyecto real.

## Cerradas

| Tema | Decisión |
| --- | --- |
| Cronómetro | 90 s fijo, documentado. `time_limit_seconds` solo admite 90. No es configurable en el MVP. |
| Ranking | Mínimo 20 preguntas distintas; orden por precisión (% de aciertos) y desempate por **tiempo promedio** por pregunta. |
| Intentos que cuentan | Solo el primer intento por pregunta y persona, en sesiones completadas. Un timeout cuenta como fallo. |
| Borrado de usuarios | En cascada (se pierde su historial). |
| Activar preguntas | Solo con `verified_at` en su clave. |
| Equipo | Cinco miembros como máximo. |
| Rol del backend | `postgres` en el MVP; `DATABASE_URL` solo en Render. |
| Nombre de la migración | `npx supabase migration new supabase_cane` → `20261009212148_supabase_cane.sql`. |
| Pruebas | Proyecto Supabase nuevo y vacío, solo para pruebas. |
| Vencimiento sin respuesta | `next` registra el timeout de la pregunta vencida y emite la siguiente; si era la última, cierra la sesión (409). |
| Validación del token | Con Supabase Auth (`GET /auth/v1/user`, equivalente a `get_user`), más perfil de equipo en la base. |
| Cambios de API para el front | B1 `server_now`, B2 `GET /ranking` y B3 `GET /sessions/{id}/attempts`: implementados. |
| Enunciados | **Markdown + LaTeX (KaTeX)**, HTML desactivado y sanitizado por lista blanca, implementado (2026-10-13). El banco real lo exigía: entre las 427 activas, 120 traen LaTeX, 8 tablas y 8 imágenes. Detalle en [`frontend-esqueleto.md`](frontend-esqueleto.md). |
| Curación del banco (2026-10-12) | Estados activa / inactiva / descartada. Las activas llevan `verified_at` y `verified_basis = decision_bloque_ready_2026-10-12`: decisión en bloque confiando en el resaltado, **no** certificación pregunta por pregunta. Listas en `scripts/curacion_2026-10-12.json`; guía en [`importador.md`](importador.md). |
| Re-importar | No reactiva ni desactiva lo que se cambió a mano: solo inserta las nuevas; `--forzar-estado` es explícito. |
| Continuar sesión | Con el id guardado en el navegador (por dispositivo). |
| Contraseñas | Sin recuperación en el MVP: la cambia el administrador desde el panel. |
| `assets` (imágenes) | En PostgreSQL (`bytea`, tabla `question_assets`) y servidas por un endpoint autenticado de FastAPI, solo de preguntas ya emitidas en una sesión propia. Sin Storage ni URLs públicas. Solo se dibujan las imágenes listadas en `assets` de la pregunta. |

Detalle y trazabilidad en [`supabase.md`](supabase.md),
[`revision-sql-supabase.md`](revision-sql-supabase.md) y
[`arquitectura.md`](arquitectura.md).

## Abiertas

### Migración y base de datos

- **Migración probada, no aplicada al real**: pasó 14/14 en el proyecto de
  pruebas aplicada con la CLI (2026-10-11). Falta la autorización explícita
  para el `db push` al proyecto real. Guía en [`supabase.md`](supabase.md).
- **Registro abierto**: `supabase/config.toml` trae `enable_signup = true`
  (valor por defecto de la CLI). Decidir si se cambia antes de cualquier
  `config push` o de usar la pila local. Verificar también el panel.

### Backend

- **Probado contra `pruebas_cane`** (2026-10-12, resultado informado por el
  usuario): Auth real, PostgreSQL real, recorrido completo, timeout con `next`,
  `server_now`, intentos y ranking. Verificado también el **aislamiento**:
  entre compañeros del mismo equipo (404 en las cinco rutas de sesión) y entre
  equipos (ranking), y el front en un navegador real con CORS.
  Sigue sin comprobarse:
  - **la Data API** con la clave publicable (que `question_keys` no devuelva
    filas, sin token y con token);
  - **qué cadena de conexión usará el backend**: la que usa el importador en
    pruebas es la del **pooler** (comprobado el 2026-10-13 por su host, sin
    mostrarla); la que se informó antes para el backend era *directa*
    (`db.<ref>.supabase.co`). Para Render hay que probar la **Session
    pooler**, porque la directa exige IPv6;
  - lector de pantalla y navegador móvil.
- **Concurrencia**: la prueba local usa PGlite (una conexión a la vez) y la
  corrida real fue secuencial, así que el `FOR UPDATE` y el pool no se
  ejercitaron en paralelo.
- **Conexión en Render**: qué cadena de *Connect* usar (directa requiere IPv6;
  *session pooler* admite IPv4) y comprobarlo al desplegar. `psycopg-binary`
  en la plataforma de Render, sin comprobar.
- **Latencia de `get_user`**: una llamada a Auth por petición. Si molesta, se
  cachea unos segundos.
- **Límite de tasa**: no hay. Con cinco usuarios es aceptable; revisar antes de
  abrir la API.
- **Tamaño de sesiones de área y aleatorias**: `question_count` lo pide el
  cliente con un tope provisional de 50 (`MAX_QUESTIONS_PER_SESSION`). No es
  una regla acordada.
- **Selección de preguntas**: hoy al azar entre las últimas revisiones activas;
  no evita repetir preguntas ya vistas entre sesiones.
- **Rutas pendientes**: repetir sesión (`repeated_from`).
- **Documentación de la API**: `/docs` y `/openapi.json` están públicos;
  decidir si se desactivan en producción.

### Datos y despliegues

Nada de esto está terminado:

- Auth, las cinco identidades del equipo y sus perfiles.
- Banco de preguntas: importador probado en local y **cargado en `pruebas_cane`
  (2026-10-13) sin figuras**: 483 preguntas (427 activas, 55 inactivas, 1
  descartada). Faltan las figuras (migración `question_assets`, pendiente de
  autorizar); en el proyecto real, nada (ver [`importador.md`](importador.md)).
- **Markdown, LaTeX y figuras: implementados y probados en local** con el
  banco real y a 390 px. Falta aplicar la migración `question_assets` a
  `pruebas_cane`, importar y repetir la prueba allí; lector de pantalla y
  teléfono real sin probar.
- Las ecuaciones destacadas anchas se desplazan en horizontal sin señal visual
  de que hay más; revisar si hace falta una pista (degradado, flecha).
- Una figura ancha (p. ej. econometría 56, dos gráficos) queda pequeña a 390 px;
  valorar tocar para ampliar.
- Despliegues en Netlify y Render, y comprobar que el frontend alcanza la API
  (CORS incluido: solo se probó el encabezado en el backend, no un navegador).

### Otros

- **Versión de Python en Render**: el backend se probó localmente con 3.14.5.
  Al desplegar hay que fijar la versión (p. ej. con `PYTHON_VERSION`) y
  comprobar que Render la admite. No se creó `runtime.txt`.
- **Servidor de Render tras inactividad**: probar su comportamiento en el plan
  gratuito antes de depender de él.
- **Simulacro**: las fases (16, 12, 8 y 4 preguntas) se basan en el reglamento
  de 2025; faltan las reglas de 2026.
- **Dependencia de pruebas**: con `httpx` 0.28 el cliente de pruebas de
  Starlette emite una advertencia de deprecación que recomienda `httpx2`. Las
  pruebas pasan; está sin decidir si migrar.
