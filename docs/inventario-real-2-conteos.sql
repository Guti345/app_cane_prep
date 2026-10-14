-- INVENTARIO DE SOLO LECTURA, ETAPA 2: CONTEOS AGREGADOS (NO SE EJECUTA TODAVÍA).
--
-- No ejecutar hasta revisar el resultado de la etapa 1 (docs/inventario-real-1-catalogo.sql)
-- y decidir qué bloques corresponden.
--
-- Cada BLOQUE es una sentencia SELECT independiente, de solo lectura, que cuenta filas de
-- UNA sola relación (o de dos, donde se indica). Se ejecuta SOLO si la etapa 1 confirmó que
-- todo lo que figura en su línea "requiere" EXISTE y se puede leer
-- (lectura_con_el_rol_actual=true). Ejecutar un bloque suelto, nunca el archivo completo:
-- una instalación parcial haría fallar los bloques que dependen de lo que falta, y ese
-- fallo no es un hallazgo sobre los datos.
--
-- Solo se devuelven totales. Nunca correos, nombres, identificadores de usuario,
-- enunciados ni respuestas. El recuento de Auth es únicamente agregado.

-- BLOQUE 1 (requiere: auth.users)
SELECT count(*)::bigint AS cuentas_auth FROM auth.users;

-- BLOQUE 2 (requiere: supabase_migrations.schema_migrations)
SELECT count(*)::bigint AS migraciones_registradas,
       coalesce(string_agg(version, ', ' ORDER BY version), '(ninguna)') AS versiones
FROM supabase_migrations.schema_migrations;

-- BLOQUE 3 (requiere: public.teams)
SELECT count(*)::bigint AS equipos FROM public.teams;

-- BLOQUE 4 (requiere: public.profiles)
SELECT count(*)::bigint AS perfiles, count(DISTINCT team_id)::bigint AS equipos_con_perfiles
FROM public.profiles;

-- BLOQUE 5 (requiere: public.questions)
SELECT count(*)::bigint AS preguntas,
       count(*) FILTER (WHERE active)::bigint AS activas
FROM public.questions;

-- BLOQUE 6 (requiere: public.questions y las columnas de la 2.ª migración)
SELECT count(*) FILTER (WHERE active)::bigint AS activas,
       count(*) FILTER (WHERE NOT active AND NOT discarded)::bigint AS inactivas,
       count(*) FILTER (WHERE discarded)::bigint AS descartadas
FROM public.questions;

-- BLOQUE 7 (requiere: public.question_keys)
SELECT count(*)::bigint AS claves, count(verified_at)::bigint AS claves_verificadas
FROM public.question_keys;

-- BLOQUE 8 (requiere: public.questions y public.question_keys)
SELECT count(*)::bigint AS activas_sin_clave_verificada
FROM public.questions q
LEFT JOIN public.question_keys k ON k.question_id = q.id
WHERE q.active AND (k.question_id IS NULL OR k.verified_at IS NULL);

-- BLOQUE 9 (requiere: public.question_assets)
SELECT count(*)::bigint AS figuras, coalesce(sum(octet_length(data)), 0)::bigint AS bytes
FROM public.question_assets;

-- BLOQUE 10 (requiere: public.sessions)
SELECT status::text AS estado, count(*)::bigint AS sesiones
FROM public.sessions GROUP BY status ORDER BY status;

-- BLOQUE 11 (requiere: public.session_questions)
SELECT count(*)::bigint AS posiciones FROM public.session_questions;

-- BLOQUE 12 (requiere: public.attempts)
SELECT count(*)::bigint AS intentos FROM public.attempts;
