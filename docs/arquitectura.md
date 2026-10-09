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
- CORS configurado por `FRONTEND_ORIGIN` (por defecto `http://localhost:5173`).
- Pantalla con un botón para consultar `/health`.

No existen: Auth, perfiles, preguntas, sesiones, ranking ni migraciones.
