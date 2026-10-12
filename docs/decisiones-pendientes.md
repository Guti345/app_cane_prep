# Decisiones

Lo cerrado y lo que sigue abierto. Una decisión "cerrada" está reflejada en la
migración, que aun así **no se ha aplicado ni ejecutado**.

## Cerradas (2026-10-09)

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

Detalle y trazabilidad en [`supabase.md`](supabase.md) y
[`revision-sql-supabase.md`](revision-sql-supabase.md).

## Abiertas

### Migración y base de datos

- **Migración probada, no aplicada al real**: la versión actual pasó 14/14 en
  el proyecto de pruebas aplicada con la CLI (2026-10-11). Falta la
  autorización explícita para el `db push` al proyecto real. Guía y
  comprobaciones previas en [`supabase.md`](supabase.md).
- **Sin cubrir en las pruebas**: modos `area` y `simulacro`, sesiones
  abandonadas, concurrencia y acceso real por la Data API. Se cubren al
  conectar el backend (parte 3).
- **Registro abierto**: `supabase/config.toml` trae `enable_signup = true`
  (valor por defecto de la CLI). Decidir si se cambia antes de cualquier
  `config push` o de usar la pila local. Verificar también el panel.
- **Regla del timeout**: queda como fallo con `90000` ms; falta documentarla
  de cara al usuario.

### API de juego (esqueleto)

- **Vencimiento sin respuesta**: hoy el cliente debe enviar `answer` con
  `selected_option = null` para registrar el timeout. Si cierra la pestaña, la
  sesión queda activa. Decidir si `next` debe registrar automáticamente el
  vencimiento de la pregunta anterior.
- **Tamaño de sesiones de área y aleatorias**: `question_count` se pide al
  cliente con un tope provisional de 50 (`MAX_QUESTIONS_PER_SESSION`). No es
  una regla acordada.
- **Selección de preguntas**: orden, aleatoriedad y qué pasa con preguntas
  repetidas entre sesiones. El SQL deja la selección a FastAPI.
- **Repetir sesión** (`repeated_from`) y **ranking** (`GET /ranking`): sin
  ruta todavía.
- **Códigos de estado**: 501 mientras no haya auth ni base; 409 para sesión
  cerrada o pregunta no emitida; 404 para sesión ajena.

### Auth, datos y despliegues

Nada de esto está terminado:

- Auth, las cinco identidades del equipo y sus perfiles.
- Autorización del API: mecanismo de validación del token de Supabase en el
  backend (parte 3).
- Importación privada del banco de preguntas (483 esperadas, no garantizadas
  como habilitadas el primer día).
- Endpoints de juego.
- Despliegues en Netlify y Render, y comprobar que el frontend alcanza la API.

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
