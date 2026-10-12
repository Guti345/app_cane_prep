# Arquitectura

Descripción de la arquitectura **elegida**. Lo que no está implementado se
marca como tal.

## Capas

| Capa | Tecnología | Destino previsto | Estado |
| --- | --- | --- | --- |
| Frontend | TypeScript + Vite, sitio estático | Netlify | Pantalla mínima; sin desplegar |
| Backend | Python + FastAPI | Render | Solo `GET /health`; sin desplegar |
| Datos y usuarios | PostgreSQL + Auth | Supabase | Sin migraciones ni Auth configurado |

Es un monorepo con una carpeta por capa (`frontend/`, `backend/`,
`supabase/`).

## Flujo

```
Navegador ──(inicio de sesión)──────────────► Supabase Auth
    │
    │  JWT del usuario (Authorization: Bearer ...)
    ▼
FastAPI ──(conexión PostgreSQL desde el servidor)──► Supabase PostgreSQL
```

- El navegador usa Supabase **solo para Auth**. No lee ni escribe las tablas
  del juego.
- Todo el contenido y las operaciones del juego pasan por FastAPI, que
  verifica la identidad y el equipo, controla el tiempo, evalúa respuestas y
  guarda los intentos.
- Las credenciales privadas viven solo en el backend, nunca en el frontend ni
  en Git.
- CORS limita qué orígenes pueden llamar a la API, pero **no sustituye** la
  autorización: cada endpoint debe verificar al usuario.

## Respuestas correctas

- Antes de responder, el navegador recibe enunciado, opciones y recursos, pero
  no la clave.
- Las claves se guardarán separadas del contenido de la pregunta (propuesta:
  tabla `question_keys`; aún no existe).
- Después de evaluar, la API puede devolver la respuesta correcta de **esa**
  pregunta.

## Cronómetro

- 90 segundos por pregunta, contados por el servidor desde que emite la
  pregunta. Recargar la página no lo reinicia.
- La configurabilidad completa del plazo no está resuelta; ver
  [`decisiones-pendientes.md`](decisiones-pendientes.md).

## Atomicidad

Las operaciones de juego que deben ser atómicas (p. ej. registrar un intento
y cerrar la pregunta) se harán con **una conexión PostgreSQL desde el
backend** y una transacción, no con varias llamadas REST independientes a
Supabase. Está pendiente de implementar; tampoco se ha elegido aún el
controlador de PostgreSQL.

## Qué existe hoy

- `GET /health` → `{"ok": true}`, sin base de datos ni claves.
- CORS configurado por `FRONTEND_ORIGIN` (por defecto `http://localhost:5173`),
  con `GET` y `POST`.
- Pantalla con un botón para consultar `/health`.
- **Esqueleto** de la API de juego, descrito abajo: solo pruebas locales, sin
  base de datos ni autenticación reales.
- Una migración SQL en `supabase/migrations/`, no aplicada al proyecto real.

No existen: Auth, perfiles, banco de preguntas, ranking en la API ni conexión
a la base de datos.

## Esqueleto de la API de juego

Contrato de las rutas que implementará la parte 3. **Hoy todas responden 501**
porque ni la autenticación ni el acceso a datos están implementados
(`backend/app/dependencies.py`); no hay modo "sin login" ni identidad
simulada.

| Ruta | Qué hace |
| --- | --- |
| `POST /sessions` | Crea la sesión y su manifiesto. Cuerpo: `mode` (`area`, `random`, `simulacro`), `area`, `stage`, `question_count`. En `simulacro` el número lo fija la fase (16/12/8/4). |
| `GET /sessions/{id}` | Estado: estado, respondidas y, si hay una pregunta pendiente, su posición y plazo. Sirve para recuperar la pantalla al recargar. |
| `POST /sessions/{id}/next` | Emite la siguiente pregunta o repite la pendiente **con el mismo plazo**. Devuelve enunciado, opciones, recursos, área, posición y `deadline_at`; nunca la clave. |
| `POST /sessions/{id}/answer` | Cuerpo: `position`, `selected_option` (`null` registra el vencimiento). Devuelve acierto, tiempo y `correct_option`. Reenviar devuelve el intento ya guardado. |
| `POST /sessions/{id}/abandon` | Cierra una sesión activa; no alimenta el ranking. |

Reglas del esqueleto:

- La identidad la da `get_current_user`, nunca el cuerpo: un campo `user_id`
  extra se rechaza (422).
- Una sesión ajena responde 404, igual que una inexistente.
- La API no calcula tiempos ni evalúa respuestas: eso lo hará el repositorio
  contra PostgreSQL, con los triggers de la migración y su reloj.
- `IssuedQuestion` no tiene campo de respuesta correcta; `Attempt` sí, porque
  solo existe después de responder.

Estructura: `domain.py` (tipos y contrato `GameRepository`), `schemas.py`,
`routes_game.py`, `dependencies.py`. Las pruebas usan un repositorio en
memoria (`backend/tests/fakes.py`) que **no** es fuente de verdad de las
reglas; estas se validan contra PostgreSQL.
