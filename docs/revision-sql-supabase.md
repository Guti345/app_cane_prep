# Revisión del SQL inicial (`supabase_cane.sql`)

Revisión por lectura del archivo real, del 2026-10-09. **No se modificó el SQL**
ni se cambió ninguna regla. El archivo original vive en
`private-data/supabase_cane.sql` (local, ignorado por Git); los números de línea
se refieren a esa copia.

> **Actualización (2026-10-09, después de las decisiones):** D1, D2, D5 y T1
> se aplicaron en `supabase/migrations/20261009212148_supabase_cane.sql`; D3,
> D4 y D6 ya eran así y no cambiaron. T2-T6 **no se aplicaron**. Las decisiones
> y su efecto están en [`supabase.md`](supabase.md). Lo que sigue es la revisión
> original, conservada tal cual; no se ha ejecutado nada.

## Qué se comprobó y qué no

| Comprobación | Resultado |
| --- | --- |
| Sin datos del banco, claves concretas, credenciales, correos, UUID ni cadenas de conexión | Sí. Los dos `INSERT` están dentro de comentarios (L357, L359). |
| Sintaxis | Válida según el parser de PostgreSQL (pglast): 47 sentencias, 9 cuerpos `plpgsql` sin error. |
| Ejecución | **No probada.** No hay Docker ni una base desechable; el SQL nunca se ha ejecutado. |
| Comportamiento de los triggers y del ranking | **No probado.** Solo lectura. |

## Inventario: coincide con lo propuesto

- 7 tablas en `public`: `teams`, `profiles`, `questions`, `question_keys`,
  `sessions`, `session_questions`, `attempts`.
- 1 vista: `public.practice_ranking` (`security_invoker = true`).
- 9 funciones en `cane_private`: `limit_team_size`, `valid_options`,
  `valid_pages`, `check_question_key`, `freeze_used_question`,
  `validate_session_question`, `grade_attempt`, `reject_attempt_update`,
  `finish_session`.
- 1 extensión (`pgcrypto`), 9 triggers, 3 índices.

## Lo que está bien (por lectura)

- RLS activado en las 7 tablas (L339-345), sin ninguna política: nada queda
  abierto por defecto.
- `REVOKE ALL` sobre tablas y vista a `PUBLIC`, `anon` y `authenticated`
  (L346-347), y sobre el esquema y las funciones de `cane_private`
  (L9, L348).
- La clave correcta está en `question_keys`, separada del contenido, y la vista
  del ranking no la expone.
- Todas las funciones fijan `search_path = ''` y usan nombres calificados.
- Doble envío: `UNIQUE(session_id, position)`. Manifiesto inmutable, intentos
  no editables, versiones de pregunta usadas congeladas.
- El servidor, no el navegador, decide plazo, acierto y tiempo
  (`grade_attempt`, L236-261).

## Puntos a resolver antes de aplicar

### Decisiones tuyas (no cambié nada)

**D1. Cronómetro: 90 s fijo en 7 sitios.** `time_limit_seconds` hoy no
configura nada: el plazo lo impone la restricción de `deadline_at`.

| Línea | Qué fija |
| --- | --- |
| L100 | `time_limit_seconds` por defecto 90 y `<= 90` (solo permite bajar) |
| L126 | `deadline_at = issued_at + interval '90 seconds'` (obligatorio) |
| L135 | `time_used_ms BETWEEN 0 AND 90000` |
| L139 | si hubo timeout, `time_used_ms = 90000` |
| L252 | `grade_attempt` fuerza `90000` al vencer |
| L257 | `least(90000, ...)` |
| L368 | el flujo documentado usa `interval '90 seconds'` |

Poner `time_limit_seconds = 60` **no** cambiaría el plazo real (seguiría en 90).
Opciones: (a) dejar 90 s fijos en el MVP y documentarlo — la recomendada por ser
la más barata y coherente con "no basta cambiar la columna"; (b) adaptar los
siete sitios para que el plazo salga de la sesión. Tampoco está documentada la
regla al vencer: hoy un timeout queda como incorrecto, sin opción y con
`90000` ms.

**D2. Desempate del ranking (L306-308, L326).** Orden actual: precisión,
**aciertos**, tiempo **medio**. Confirmado solo: precisión y luego tiempo.
Decidir (i) tiempo total o medio, y (ii) si "aciertos" se quita. Ojo: con
tiempo total y distinto número de preguntas vistas, el total favorece a quien
respondió menos.

**D3. Qué intentos cuentan (L310-317).** El SQL toma la primera respuesta por
pregunta fuente (`bank_id`, `source_id`) y persona en sesiones completadas.
Consecuencias a confirmar:

- Un timeout cuenta como primera respuesta (incorrecta, 90 s): repetir no la
  corrige.
- Las revisiones de una misma pregunta se agrupan: si se corrige una clave en
  una revisión nueva, la primera respuesta sobre la antigua sigue contando.
- El mínimo de 20 es de preguntas fuente distintas (coincide con lo confirmado).

**D4. Borrado en cascada (L17, L95, L118, L137).** Borrar un usuario de Auth
borra su perfil y, en cascada, sus sesiones, manifiestos e intentos. El ranking
perdería ese historial. Decidir si se acepta o si se prefiere desactivar
perfiles en lugar de borrar.

**D5. Activar sin verificar (L83-88, L160-161).** Una pregunta puede quedar
`ready`/`active` con clave pero sin `verified_at`. Decidir si activar debe
exigir verificación, dado que transcribir el resaltado no certifica la
respuesta.

**D6. Tope de cinco miembros (L23-36).** Fijo en 5 por equipo; un sexto perfil
(p. ej. un suplente) falla. Confirmar que es lo deseado.

### Puntos técnicos (propongo; no se aplicaron)

**T1. Rol del backend vs `service_role` (L349-353).** El SQL concede permisos
solo a `service_role`, el rol de la API REST de Supabase. Pero la arquitectura
elegida es una **conexión PostgreSQL directa** (`DATABASE_URL`). Según el rol
que use esa cadena:

- Si es `postgres`, los `GRANT` a `service_role` no se usan y el backend tiene
  privilegios totales (no "acotados").
- Si es un rol propio, necesita `USAGE` en `cane_private` y `EXECUTE` en sus
  funciones: las `CHECK` y los triggers las invocan con los privilegios de quien
  inserta. El SQL no lo crea.

Hay que definir qué rol usará FastAPI antes de aplicar. Es la decisión técnica
más importante de la lista.

**T2. `pgcrypto` innecesaria (L7).** `gen_random_uuid()` es nativa desde
PostgreSQL 13 y no se usa nada más de la extensión. Instalada así, queda en
`public`, que Supabase suele señalar como advertencia. Propuesta: quitarla, o
instalarla `WITH SCHEMA extensions`.

**T3. Privilegios por defecto y Data API.** Los `REVOKE` cubren los objetos
existentes. Supabase suele conceder por defecto a `anon`/`authenticated` los
objetos nuevos de `public`; tablas futuras quedarían abiertas salvo que se
corrija. Como la arquitectura es API-only, valorar `ALTER DEFAULT PRIVILEGES` o
no exponer `public` en la Data API (decisión de panel). A verificar en el
proyecto real.

**T4. `BEGIN`/`COMMIT` explícitos (L6, L354).** La CLI ya ejecuta la migración
dentro de su propio flujo y registra el historial. Un `COMMIT` interno podría
dejar la migración aplicada pero sin registrar si algo falla después. Probar
en una base desechable; si es un problema, quitarlos.

**T5. `repeated_from` + sesiones cerradas (L102, L278).** `ON DELETE SET NULL`
actualiza la sesión que repite; `finish_session` rechaza cualquier cambio en
una sesión cerrada ("Sesión cerrada"). Podría impedir borrar una sesión
original (o usuario por cascada). Plausible por lectura, **no verificado**.

**T6. Menor.** Sin índices en `sessions(team_id)`, `profiles(team_id)` ni
`session_questions(question_id)`; irrelevante con ~500 preguntas y 5 usuarios.
Tras una sesión completada, un reintento de respuesta recibe "Sesión no
activa" y no la violación de unicidad: el API debe manejar ambos casos (L241).

## Qué falta para aplicar con confianza

1. Tus decisiones D1-D6 y la de T1.
2. Probar el SQL en una base **desechable** (local con Docker, o un proyecto
   Supabase nuevo y vacío creado para pruebas, nunca el real): ejecución,
   triggers, ranking, plazo. Hoy no hay Docker en este equipo.
3. Nombre de la migración (ver [`supabase.md`](supabase.md)).
4. Autorización explícita para `db push`.

Estado de esta migración: **pendiente de revisión y aplicación**. Que el SQL
esté en el repo o en `private-data/` no lo convierte en regla definitiva.
