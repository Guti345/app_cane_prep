# Decisiones

Lo cerrado y lo que sigue abierto. Una decisión "cerrada" está reflejada en la
migración, que aun así **no se ha aplicado ni ejecutado**.

## Cerradas (2026-10-09)

| Tema | Decisión |
| --- | --- |
| Cronómetro | 90 s fijo, documentado. `time_limit_seconds` solo admite 90. No es configurable en el MVP. |
| Ranking | Mínimo 20 preguntas distintas; orden por precisión (% de aciertos) y desempate por **tiempo total**. |
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

- **Probar la migración**: sin ejecutar en ninguna base. Pendiente crear el
  proyecto de pruebas y correr [`prueba-migracion.sql`](prueba-migracion.sql)
  (sin Docker en este equipo).
- **Puntos técnicos T2-T6** de la revisión, sin aplicar: `pgcrypto`, permisos
  por defecto y Data API, `BEGIN`/`COMMIT` internos, `repeated_from` frente a
  sesiones cerradas, índices. Se decidirán con el resultado de la prueba.
- **Aplicar al proyecto real**: requiere autorización explícita tras una
  prueba aprobada.
- **Registro abierto**: `supabase/config.toml` trae `enable_signup = true`
  (valor por defecto de la CLI). Decidir si se cambia antes de cualquier
  `config push` o de usar la pila local. Verificar también el panel.
- **Regla del timeout**: queda como fallo con `90000` ms; falta documentarla
  de cara al usuario.

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
