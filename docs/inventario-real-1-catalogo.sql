-- INVENTARIO DE SOLO LECTURA, ETAPA 1: CATÁLOGO. Una sola sentencia SELECT.
-- Solo mira el catálogo de PostgreSQL: no lee tablas (ni auth.users), no escribe nada y no
-- devuelve claves, correos, datos ni respuestas. Ausente = "NO EXISTE"; presente pero sin
-- permiso de lectura = existe con lectura_con_el_rol_actual=false. Un error NO es "base vacía".
-- Resultado: seccion | elemento | valor.

WITH
exp_rel(s, n) AS (VALUES
  ('public', 'teams'), ('public', 'profiles'), ('public', 'questions'),
  ('public', 'question_keys'), ('public', 'sessions'), ('public', 'session_questions'),
  ('public', 'attempts'), ('public', 'question_assets'), ('public', 'practice_ranking')),
-- Relaciones de Supabase que consultará la etapa 2 (se confirman aquí, no se asumen).
ref_rel(s, n) AS (VALUES
  ('auth', 'users'), ('supabase_migrations', 'schema_migrations')),
exp_col(s, t, c) AS (VALUES
  ('public', 'questions', 'discarded'), ('public', 'questions', 'review_reason'),
  ('public', 'questions', 'duplicate_of'), ('public', 'questions', 'review_note'),
  ('public', 'question_keys', 'verified_basis')),
exp_fn(n) AS (VALUES
  ('limit_team_size'), ('valid_options'), ('valid_pages'), ('check_question_key'),
  ('freeze_used_question'), ('validate_session_question'), ('grade_attempt'),
  ('reject_attempt_update'), ('finish_session')),
exp_trg(t, n) AS (VALUES
  ('profiles', 'profiles_limit'), ('questions', 'questions_key_check'),
  ('question_keys', 'keys_question_check'), ('questions', 'questions_freeze'),
  ('question_keys', 'keys_freeze'), ('session_questions', 'session_questions_guard'),
  ('attempts', 'attempts_grade'), ('attempts', 'attempts_immutable'),
  ('sessions', 'sessions_finish'), ('question_assets', 'question_assets_freeze')),
exp_idx(n) AS (VALUES ('questions_pool'), ('sessions_person'), ('attempts_session')),
-- Esquemas internos habituales de Supabase/PostgreSQL (no son de la aplicación).
internal_ns(n) AS (VALUES
  ('auth'), ('storage'), ('extensions'), ('graphql'), ('graphql_public'), ('realtime'),
  ('vault'), ('pgsodium'), ('pgsodium_masks'), ('supabase_functions'),
  ('supabase_migrations'), ('net'), ('cron'), ('pgbouncer'), ('_realtime'),
  ('_analytics'), ('_supavisor'), ('information_schema'), ('pgtle')),
rel AS (
  SELECT n.nspname AS s, c.relname AS n, c.oid, c.relkind
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
),
found_rel AS (
  SELECT e.s, e.n, r.oid, r.relkind
  FROM exp_rel e LEFT JOIN rel r ON r.s = e.s AND r.n = e.n AND r.relkind IN ('r', 'p', 'v', 'm')
),
found_col AS (
  SELECT e.s, e.t, e.c,
         EXISTS (SELECT 1 FROM pg_attribute a
                 JOIN pg_class c ON c.oid = a.attrelid
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = e.s AND c.relname = e.t AND a.attname = e.c
                   AND a.attnum > 0 AND NOT a.attisdropped) AS ok
  FROM exp_col e
),
found_fn AS (
  SELECT f.n,
         EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'cane_private' AND p.proname = f.n) AS ok
  FROM exp_fn f
),
found_trg AS (
  SELECT e.t, e.n,
         EXISTS (SELECT 1 FROM pg_trigger g
                 JOIN pg_class c ON c.oid = g.tgrelid
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relname = e.t AND g.tgname = e.n
                   AND NOT g.tgisinternal) AS ok
  FROM exp_trg e
),
found_idx AS (
  SELECT e.n,
         EXISTS (SELECT 1 FROM rel r WHERE r.s = 'public' AND r.n = e.n AND r.relkind = 'i') AS ok
  FROM exp_idx e
),
-- Lo que hay en los esquemas de la aplicación y no es de CANE.
-- Los objetos que pertenecen a una extensión (pg_depend, deptype 'e') no son ajenos: se
-- cuentan aparte. En Supabase las extensiones suelen estar en el esquema extensions.
foreign_rel AS (
  SELECT r.s, r.n, r.relkind
  FROM rel r
  WHERE r.s IN ('public', 'cane_private')
    AND r.relkind IN ('r', 'p', 'v', 'm', 'f', 'S', 'c')
    AND NOT EXISTS (SELECT 1 FROM exp_rel e WHERE e.s = r.s AND e.n = r.n)
    AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.classid = 'pg_class'::regclass AND d.objid = r.oid AND d.deptype = 'e')
),
foreign_fn AS (
  SELECT n.nspname AS s, p.proname AS n, p.oid
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname IN ('public', 'cane_private')
    AND NOT (n.nspname = 'cane_private'
             AND EXISTS (SELECT 1 FROM exp_fn f WHERE f.n = p.proname))
    AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
),
foreign_type AS (
  SELECT n.nspname AS s, t.typname AS n, t.typtype
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
  WHERE n.nspname IN ('public', 'cane_private') AND t.typtype IN ('e', 'd', 'r', 'm')
    AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
),
ext_objects AS (
  SELECT count(*) AS n FROM pg_depend d
  WHERE d.deptype = 'e'
    AND ((d.classid = 'pg_proc'::regclass
          AND d.objid IN (SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                          WHERE n.nspname IN ('public', 'cane_private')))
         OR (d.classid = 'pg_class'::regclass
             AND d.objid IN (SELECT r.oid FROM rel r WHERE r.s IN ('public', 'cane_private'))))
)

SELECT * FROM (

  -- Resumen: ¿la instalación de CANE está completa, parcial o ausente?
  SELECT 'resumen' AS seccion, 'relaciones de CANE presentes' AS elemento,
         (SELECT count(*) FROM found_rel WHERE oid IS NOT NULL) || ' de ' ||
         (SELECT count(*) FROM exp_rel) AS valor
  UNION ALL SELECT 'resumen', 'columnas de la 2.ª migración presentes',
         (SELECT count(*) FROM found_col WHERE ok) || ' de ' || (SELECT count(*) FROM exp_col)
  UNION ALL SELECT 'resumen', 'funciones de cane_private presentes',
         (SELECT count(*) FROM found_fn WHERE ok) || ' de ' || (SELECT count(*) FROM exp_fn)
  UNION ALL SELECT 'resumen', 'triggers presentes',
         (SELECT count(*) FROM found_trg WHERE ok) || ' de ' || (SELECT count(*) FROM exp_trg)
  UNION ALL SELECT 'resumen', 'índices presentes',
         (SELECT count(*) FROM found_idx WHERE ok) || ' de ' || (SELECT count(*) FROM exp_idx)
  UNION ALL SELECT 'resumen', 'esquema cane_private',
         CASE WHEN EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cane_private')
              THEN 'existe' ELSE 'NO EXISTE' END
  UNION ALL SELECT 'resumen', 'objetos AJENOS en public/cane_private',
         ((SELECT count(*) FROM foreign_rel) + (SELECT count(*) FROM foreign_fn)
          + (SELECT count(*) FROM foreign_type))::text
  UNION ALL SELECT 'resumen', 'objetos de extensiones en public/cane_private (no son ajenos)',
         (SELECT n FROM ext_objects)::text

  -- Relaciones esperadas de CANE y de Supabase: existe / NO EXISTE, y si este rol las lee.
  UNION ALL
  SELECT 'relaciones_esperadas', f.s || '.' || f.n,
         CASE WHEN f.oid IS NULL THEN 'NO EXISTE'
              ELSE 'existe; tipo=' || CASE f.relkind WHEN 'v' THEN 'vista' WHEN 'm' THEN 'vista materializada' ELSE 'tabla' END
                   || '; lectura_con_el_rol_actual=' || has_table_privilege(f.oid, 'SELECT') END
  FROM found_rel f
  UNION ALL
  SELECT 'relaciones_esperadas', r.s || '.' || r.n,
         CASE WHEN x.oid IS NULL THEN 'NO EXISTE'
              ELSE 'existe; lectura_con_el_rol_actual=' || has_table_privilege(x.oid, 'SELECT') END
  FROM ref_rel r
  LEFT JOIN rel x ON x.s = r.s AND x.n = r.n AND x.relkind IN ('r', 'p', 'v', 'm')

  UNION ALL
  SELECT 'columnas_esperadas', s || '.' || t || '.' || c,
         CASE WHEN ok THEN 'existe' ELSE 'NO EXISTE' END
  FROM found_col

  UNION ALL
  SELECT 'funciones_esperadas', 'cane_private.' || n, CASE WHEN ok THEN 'existe' ELSE 'NO EXISTE' END
  FROM found_fn

  UNION ALL
  SELECT 'triggers_esperados', 'public.' || t || ' / ' || n, CASE WHEN ok THEN 'existe' ELSE 'NO EXISTE' END
  FROM found_trg

  UNION ALL
  SELECT 'indices_esperados', 'public.' || n, CASE WHEN ok THEN 'existe' ELSE 'NO EXISTE' END
  FROM found_idx

  -- Objetos AJENOS a CANE en los esquemas de la aplicación.
  UNION ALL
  SELECT 'ajenos', 'relacion ' || s || '.' || n,
         'tipo=' || CASE relkind WHEN 'r' THEN 'tabla' WHEN 'p' THEN 'tabla particionada'
                                 WHEN 'v' THEN 'vista' WHEN 'm' THEN 'vista materializada'
                                 WHEN 'f' THEN 'tabla foránea' WHEN 'S' THEN 'secuencia'
                                 ELSE 'tipo compuesto' END
  FROM foreign_rel
  UNION ALL
  SELECT 'ajenos', 'funcion ' || s || '.' || n || '(' || pg_get_function_identity_arguments(oid) || ')',
         'security_definer=' || (SELECT prosecdef FROM pg_proc WHERE pg_proc.oid = foreign_fn.oid)
  FROM foreign_fn
  UNION ALL
  SELECT 'ajenos', 'tipo ' || s || '.' || n, 'typtype=' || typtype::text
  FROM foreign_type

  -- Esquemas, clasificados.
  UNION ALL
  SELECT 'esquemas', n.nspname,
         CASE WHEN n.nspname IN ('public', 'cane_private') THEN 'APLICACION'
              WHEN n.nspname IN (SELECT i.n FROM internal_ns i) THEN 'INTERNO (Supabase/PostgreSQL)'
              ELSE 'OTRO (no reconocido)' END
         || '; propietario=' || pg_get_userbyid(n.nspowner)
  FROM pg_namespace n
  WHERE n.nspname !~ '^pg_'

  -- Todo lo que hay en public y cane_private: tablas, vistas y estado de RLS.
  UNION ALL
  SELECT 'tablas', r.s || '.' || r.n,
         'tipo=' || CASE c.relkind WHEN 'r' THEN 'tabla' WHEN 'v' THEN 'vista'
                                   WHEN 'm' THEN 'vista materializada'
                                   WHEN 'p' THEN 'tabla particionada' ELSE 'tabla foránea' END
         || '; rls=' || c.relrowsecurity || '; rls_forzada=' || c.relforcerowsecurity
         || '; propietario=' || pg_get_userbyid(c.relowner)
         || CASE WHEN c.relkind = 'v'
                 THEN '; opciones=' || coalesce(c.reloptions::text, '-') ELSE '' END
  FROM rel r JOIN pg_class c ON c.oid = r.oid
  WHERE r.s IN ('public', 'cane_private') AND r.relkind IN ('r', 'p', 'v', 'm', 'f')

  -- Permisos de tablas y vistas para los roles del cliente (anon, authenticated) y PUBLIC.
  UNION ALL
  SELECT 'permisos_tablas', r.s || '.' || r.n,
         coalesce((SELECT string_agg(coalesce(ro.rolname, 'PUBLIC') || ':' || a.privilege_type,
                                     ', ' ORDER BY coalesce(ro.rolname, 'PUBLIC'), a.privilege_type)
                   FROM aclexplode(c.relacl) a LEFT JOIN pg_roles ro ON ro.oid = a.grantee
                   WHERE coalesce(ro.rolname, 'PUBLIC') IN ('anon', 'authenticated', 'PUBLIC')),
                  '(sin permisos para anon/authenticated/PUBLIC)')
  FROM rel r JOIN pg_class c ON c.oid = r.oid
  WHERE r.s IN ('public', 'cane_private') AND r.relkind IN ('r', 'p', 'v', 'm', 'f')

  -- Permisos a nivel de columna (si los hubiera).
  UNION ALL
  SELECT 'permisos_columnas', r.s || '.' || r.n || '.' || a.attname,
         (SELECT string_agg(coalesce(ro.rolname, 'PUBLIC') || ':' || x.privilege_type, ', ')
          FROM aclexplode(a.attacl) x LEFT JOIN pg_roles ro ON ro.oid = x.grantee
          WHERE coalesce(ro.rolname, 'PUBLIC') IN ('anon', 'authenticated', 'PUBLIC'))
  FROM pg_attribute a JOIN rel r ON r.oid = a.attrelid
  WHERE r.s IN ('public', 'cane_private') AND a.attacl IS NOT NULL AND NOT a.attisdropped

  -- Uso de los esquemas por los roles del cliente.
  UNION ALL
  SELECT 'permisos_esquemas', s.n || ' -> ' || ro.n,
         CASE WHEN to_regrole(ro.n) IS NULL THEN 'el rol no existe'
              WHEN NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s.n) THEN 'el esquema no existe'
              ELSE 'USAGE=' || has_schema_privilege(ro.n, s.n, 'USAGE') END
  FROM (VALUES ('public'), ('cane_private')) AS s(n)
  CROSS JOIN (VALUES ('anon'), ('authenticated')) AS ro(n)

  -- Funciones de los esquemas de la aplicación (nombre, definer, quién puede ejecutarlas).
  UNION ALL
  SELECT 'funciones', n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
         'security_definer=' || p.prosecdef
         || CASE WHEN to_regrole('anon') IS NULL THEN ''
                 ELSE '; anon_ejecuta=' || has_function_privilege('anon', p.oid, 'EXECUTE') END
         || CASE WHEN to_regrole('authenticated') IS NULL THEN ''
                 ELSE '; authenticated_ejecuta=' || has_function_privilege('authenticated', p.oid, 'EXECUTE') END
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname IN ('public', 'cane_private')

  -- Permisos por defecto para objetos futuros (ALTER DEFAULT PRIVILEGES).
  UNION ALL
  SELECT 'permisos_por_defecto',
         pg_get_userbyid(d.defaclrole) || ' en ' || coalesce(n.nspname, '(todos los esquemas)')
         || ' [' || d.defaclobjtype::text || ']',
         coalesce((SELECT string_agg(coalesce(ro.rolname, 'PUBLIC') || ':' || a.privilege_type,
                                     ', ' ORDER BY coalesce(ro.rolname, 'PUBLIC'), a.privilege_type)
                   FROM aclexplode(d.defaclacl) a LEFT JOIN pg_roles ro ON ro.oid = a.grantee
                   WHERE coalesce(ro.rolname, 'PUBLIC')
                         IN ('anon', 'authenticated', 'service_role', 'PUBLIC')),
                  '(ninguno)')
  FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace

  -- Políticas de RLS (solo nombres y comandos; no el contenido).
  UNION ALL
  SELECT 'politicas_rls', p.schemaname || '.' || p.tablename,
         count(*) || ' politica(s): '
         || string_agg(p.policyname || ' (' || p.cmd || ' para ' || array_to_string(p.roles, ',') || ')',
                       '; ' ORDER BY p.policyname)
  FROM pg_policies p
  WHERE p.schemaname IN ('public', 'cane_private')
  GROUP BY p.schemaname, p.tablename

  -- Esquemas que expone la Data API: solo ese ajuste del rol authenticator, no el resto.
  UNION ALL
  SELECT 'data_api', 'authenticator: pgrst.db_schemas',
         coalesce((SELECT string_agg(x, ' | ') FROM pg_roles r, unnest(r.rolconfig) AS x
                   WHERE r.rolname = 'authenticator' AND x LIKE 'pgrst.db_schemas=%'),
                  '(no configurado en el rol authenticator)')

  -- Extensiones instaladas (nombre y versión).
  UNION ALL
  SELECT 'extensiones', e.extname, 'version=' || e.extversion FROM pg_extension e

  -- Conexión (la identidad del proyecto se confirma en el panel, no con SQL).
  UNION ALL
  SELECT 'conexion', 'base de datos / rol', current_database() || ' / ' || current_user
  UNION ALL
  SELECT 'conexion', 'version', split_part(version(), ' on ', 1)

) AS inventario
ORDER BY seccion, elemento;
