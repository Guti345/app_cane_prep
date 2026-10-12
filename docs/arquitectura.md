# Arquitectura

Descripción de la arquitectura **elegida**. Lo que no está desplegado ni
probado contra Supabase se marca como tal.

## Capas

| Capa | Tecnología | Destino previsto | Estado |
| --- | --- | --- | --- |
| Frontend | TypeScript + Vite, sitio estático | Netlify | Pantalla mínima; sin login ni juego; sin desplegar |
| Backend | Python + FastAPI | Render | API de juego implementada y probada en local; sin desplegar |
| Datos y usuarios | PostgreSQL + Auth | Supabase | Migración probada en un proyecto de pruebas; sin aplicar al real |

Es un monorepo con una carpeta por capa (`frontend/`, `backend/`,
`supabase/`).

## Flujo

```
Navegador ──(inicio de sesión)──────────────► Supabase Auth
    │                                              ▲
    │  Authorization: Bearer <token del usuario>   │ GET /auth/v1/user
    ▼                                              │ (valida el token)
FastAPI ───────────────────────────────────────────┘
    │
    └──(conexión PostgreSQL desde el servidor)──► Supabase PostgreSQL
```

- El navegador usa Supabase **solo para Auth**. No lee ni escribe las tablas
  del juego.
- Todo el contenido y las operaciones del juego pasan por FastAPI.
- Las credenciales privadas (`DATABASE_URL`) viven solo en el backend, nunca en
  el frontend ni en Git.
- CORS limita qué orígenes pueden llamar a la API, pero **no sustituye** la
  autorización: cada endpoint de juego exige identidad verificada.

## Autenticación

Implementada en `backend/app/supabase_auth.py` y `dependencies.py`:

1. El navegador envía `Authorization: Bearer <access_token>`.
2. El backend pregunta a Supabase Auth (`GET {SUPABASE_URL}/auth/v1/user`, con
   la clave publicable en `apikey`). Auth rechaza tokens vencidos, revocados o
   de usuarios bloqueados.
3. Con el `id` devuelto, busca el perfil en `public.profiles` para obtener el
   equipo. Tener cuenta en Auth no basta: sin perfil, 403.

| Situación | Respuesta |
| --- | --- |
| Falta el encabezado, no es `Bearer` o el token no vale | 401 |
| Token válido pero sin perfil | 403 |
| Auth no responde o responde 429/5xx | 503 |
| Falta configuración (`SUPABASE_*` o `DATABASE_URL`) | 503 |

La identidad sale solo de aquí: un `user_id` en el cuerpo o en la URL se ignora
o se rechaza. Costo: una llamada a Auth por petición (aceptable para cinco
usuarios; si hiciera falta, se cachearía unos segundos).

## Respuestas correctas

- Antes de responder, el navegador recibe enunciado, opciones y recursos, pero
  no la clave: `IssuedQuestion` no tiene campo para ella y las consultas de
  preguntas nombran sus columnas (nunca `SELECT *`).
- Las claves están en `question_keys`, separadas del contenido.
- Después de responder, la API devuelve la respuesta correcta de **esa**
  pregunta.

## Cronómetro

- 90 segundos por pregunta, fijos en el MVP. El plazo lo fija la base de datos
  con un único `clock_timestamp()` al emitir la pregunta; recargar no lo
  reinicia.
- `next` registra el timeout de la pregunta pendiente si ya venció y emite la
  siguiente. Si era la última, cierra la sesión y responde 409.
- Una respuesta tardía se registra como timeout (fallo, sin opción, 90000 ms).

## Atomicidad

Cada operación de juego es una transacción sobre **una conexión PostgreSQL
directa** (`psycopg` 3 con pool), no varias llamadas REST. La fila de la sesión
se bloquea (`FOR UPDATE`), así que dos peticiones sobre la misma sesión se
serializan. Sin sentencias preparadas, para ser compatible con el pooler en
modo transacción; SSL por defecto (`sslmode=require`).

## API de juego

| Ruta | Qué hace |
| --- | --- |
| `POST /sessions` | Crea la sesión y su manifiesto completo. Cuerpo: `mode` (`area`, `random`, `simulacro`), `area`, `stage`, `question_count`. En `simulacro` el número lo fija la fase (16/12/8/4). |
| `GET /sessions/{id}` | Estado: estado, respondidas y, si hay una pregunta pendiente, su posición y plazo. |
| `POST /sessions/{id}/next` | Emite la siguiente pregunta o repite la pendiente **con el mismo plazo**; registra timeouts vencidos. Nunca devuelve la clave. |
| `POST /sessions/{id}/answer` | Cuerpo: `position`, `selected_option` (`null` registra el vencimiento). Devuelve acierto, tiempo y `correct_option`. Reenviar devuelve el intento ya guardado. |
| `POST /sessions/{id}/abandon` | Cierra una sesión activa; no alimenta el ranking. |

- Una sesión ajena responde 404, igual que una inexistente.
- Las preguntas se eligen entre las **últimas revisiones activas y `ready`** de
  cada pregunta fuente, al azar; en simulacro, con el mismo cupo por área.
- Estructura: `domain.py` (tipos y contrato `GameRepository`), `schemas.py`,
  `routes_game.py`, `dependencies.py`, `supabase_auth.py`, `postgres.py`.

## Pruebas

| Capa | Dónde | Qué prueba |
| --- | --- | --- |
| Rutas y contrato | `tests/test_game_api.py`, `tests/test_auth.py` | HTTP con un repositorio en memoria y un verificador falso. |
| Repositorio real | `tests/integration/` | `PostgresGameRepository` contra **la migración real** en un PostgreSQL local (PGlite). Cada prueba corre en una transacción que se revierte. |

Límites de las pruebas de integración: PGlite es PostgreSQL real, pero **no es
Supabase** (versión 18.3; los roles `anon`, `authenticated`, `service_role` y
`auth.users` son simulados) y atiende una conexión a la vez, así que no cubren
concurrencia ni el pooler. Tampoco prueban la llamada real a Supabase Auth ni
la Data API.

## Qué existe hoy

- `GET /health` → `{"ok": true}`, sin base de datos ni claves.
- API de juego completa en local (sesiones, preguntas, respuestas, abandono),
  con autenticación por Supabase Auth y repositorio PostgreSQL.
- Pantalla con un botón para consultar `/health`.
- Una migración SQL, probada en un proyecto de pruebas y **no aplicada al
  proyecto real**.

No existen: login en el frontend, banco de preguntas cargado, usuarios y
perfiles del equipo, endpoint de ranking, despliegues.
