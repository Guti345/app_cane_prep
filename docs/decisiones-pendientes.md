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
| Enunciados | Texto plano en la fase 2; Markdown/LaTeX después. |
| Continuar sesión | Con el id guardado en el navegador (por dispositivo). |
| Contraseñas | Sin recuperación en el MVP: la cambia el administrador desde el panel. |
| `assets` (imágenes) | Pendiente hasta el importador; el cliente no los dibuja todavía. |

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

- **Sin probar contra Supabase real**: la llamada a `/auth/v1/user`, el
  pooler y la Data API solo se probaron con un Auth falso y PostgreSQL local
  (PGlite). Falta probarlos contra el proyecto de pruebas con `DATABASE_URL` y
  un usuario real.
- **Concurrencia**: PGlite atiende una conexión a la vez, así que el
  `FOR UPDATE` y el pool no se ejercitaron en paralelo.
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
- Importación privada del banco de preguntas (483 esperadas, no garantizadas
  como habilitadas el primer día).
- Frontend: Markdown/LaTeX, recursos (imágenes), prueba en un navegador real
  y con lector de pantalla, y pulido móvil. Las pantallas existen y están
  probadas en local, no contra `pruebas_cane`.
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
