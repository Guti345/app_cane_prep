-- PRUEBA DE LA MIGRACION 4, VERIFICACION: ejecutar DESPUES de aplicarla.
-- Comprueba que service_role ya no tiene acceso a question_keys ni question_assets y devuelve
-- el mismo estado que la linea base para compararlo (las 'huellas' deben coincidir).
-- Prueba efectiva: el bloque DO cambia a service_role SOLO dentro de una transaccion
-- (SET LOCAL) y ejecuta PERFORM 1 ... LIMIT 1: no devuelve ni muestra ninguna fila, clave
-- ni byte aunque el permiso siguiera vigente. Si el acceso funcionara, lanza FALLO y el
-- script se detiene con un error. RESET ROLE final: no queda ningun rol cambiado.
-- Solo lecturas de catalogo. No ejecuta INSERT, UPDATE, DELETE, GRANT, REVOKE ni DDL.
-- Ejecutar SOLO en el SQL Editor del proyecto pruebas_cane (referencia yqhtmrlwxgvxyiekzscb):
-- comprueba nombre y referencia en el panel antes de pegarlo. NO usar en el proyecto real.
-- El resultado es una tabla seccion | elemento | valor sin claves, bytes ni datos personales.

DO $prueba$
BEGIN
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM 1 FROM public.question_keys LIMIT 1;
    RAISE EXCEPTION 'FALLO: service_role pudo consultar public.question_keys';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
  BEGIN
    PERFORM 1 FROM public.question_assets LIMIT 1;
    RAISE EXCEPTION 'FALLO: service_role pudo consultar public.question_assets';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
  RESET ROLE;
END
$prueba$;

RESET ROLE;

WITH
roles(role) AS (VALUES ('service_role'), ('anon'), ('authenticated')),
privs(p) AS (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')),
cprivs(p) AS (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('REFERENCES')),
secret(n) AS (VALUES ('question_keys'), ('question_assets')),
expected_tables(n) AS (VALUES ('teams'), ('profiles'), ('questions'), ('question_keys'),
  ('sessions'), ('session_questions'), ('attempts'), ('question_assets')),
app_rel AS (
  SELECT c.oid, n.nspname AS s, c.relname AS n, c.relkind, c.relowner,
         c.relrowsecurity AS rls, c.relforcerowsecurity AS frls, c.relacl
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('public', 'cane_private') AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
),
acl_rows AS (
  SELECT r.s || '.' || r.n AS obj, pg_get_userbyid(a.grantor) AS grantor,
         CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
         a.privilege_type AS priv, a.is_grantable AS grantable
  FROM app_rel r
  CROSS JOIN LATERAL aclexplode(coalesce(r.relacl, acldefault('r', r.relowner))) a
),
col_rows AS (
  SELECT r.s || '.' || r.n || '.' || t.attname AS obj, r.s || '.' || r.n AS rel,
         pg_get_userbyid(a.grantor) AS grantor,
         CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
         a.privilege_type AS priv
  FROM app_rel r JOIN pg_attribute t ON t.attrelid = r.oid
  CROSS JOIN LATERAL aclexplode(t.attacl) a
  WHERE t.attacl IS NOT NULL AND NOT t.attisdropped
),
eff AS (
  SELECT ro.role, r.s || '.' || r.n AS obj,
         coalesce(string_agg(p.p, ',' ORDER BY p.p)
                  FILTER (WHERE has_table_privilege(ro.role, r.oid, p.p)), '(ninguno)') AS privs
  FROM app_rel r CROSS JOIN roles ro CROSS JOIN privs p
  WHERE r.s = 'public'
  GROUP BY ro.role, r.s, r.n
),
eff_col AS (
  SELECT ro.role, r.s || '.' || r.n AS obj,
         coalesce(string_agg(a.attname || ':' || cp.p, ',' ORDER BY a.attnum, cp.p)
                  FILTER (WHERE has_column_privilege(ro.role, r.oid, a.attnum, cp.p)), '(ninguno)') AS privs
  FROM app_rel r
  JOIN secret sx ON sx.n = r.n AND r.s = 'public'
  JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum > 0 AND NOT a.attisdropped
  CROSS JOIN roles ro CROSS JOIN cprivs cp
  GROUP BY ro.role, r.s, r.n
),
fn_rows AS (
  SELECT p.oid::regprocedure::text AS fn, pg_get_userbyid(p.proowner) AS owner, p.prosecdef,
         coalesce(p.proconfig::text, '-') AS config, coalesce(p.proacl::text, '-') AS acl
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname IN ('public', 'cane_private')
),
trg_rows AS (
  SELECT r.s || '.' || r.n || ' / ' || g.tgname AS trg, g.tgenabled::text AS enabled
  FROM pg_trigger g JOIN app_rel r ON r.oid = g.tgrelid
  WHERE NOT g.tgisinternal
),
pol_rows AS (
  SELECT p.schemaname || '.' || p.tablename || ' / ' || p.policyname AS pol,
         p.cmd || ' para ' || array_to_string(p.roles, ',') AS what
  FROM pg_policies p WHERE p.schemaname IN ('public', 'cane_private')
),
ns_rows AS (
  SELECT n.nspname AS s, pg_get_userbyid(n.nspowner) AS owner, coalesce(n.nspacl::text, '-') AS acl
  FROM pg_namespace n WHERE n.nspname IN ('public', 'cane_private')
),
member_rows AS (
  SELECT pg_get_userbyid(m.member) AS member, pg_get_userbyid(m.roleid) AS role_name,
         (to_jsonb(m) - 'oid' - 'roleid' - 'member' - 'grantor')::text AS opts
  FROM pg_auth_members m
  WHERE pg_get_userbyid(m.member) IN ('service_role', 'anon', 'authenticated', 'authenticator', 'postgres')
     OR pg_get_userbyid(m.roleid) IN ('service_role', 'anon', 'authenticated', 'authenticator')
),
secret_access AS (
  SELECT ro.rolname, r.n,
         string_agg(p.p, ',' ORDER BY p.p) AS privs,
         (ro.oid = r.relowner) AS is_owner,
         pg_has_role(ro.oid, (SELECT oid FROM pg_roles WHERE rolname = 'service_role'), 'USAGE') AS inherits_service_role
  FROM pg_roles ro
  CROSS JOIN app_rel r JOIN secret s ON s.n = r.n AND r.s = 'public'
  CROSS JOIN privs p
  WHERE NOT ro.rolsuper AND has_table_privilege(ro.oid, r.oid, p.p)
  GROUP BY ro.rolname, r.n, ro.oid, r.relowner
),
stable_state AS (
  SELECT 'acl_resto' AS k, obj || '|' || grantor || '|' || grantee || '|' || priv || '|' || grantable AS v
  FROM acl_rows
  WHERE NOT (grantee = 'service_role' AND obj IN ('public.question_keys', 'public.question_assets'))
  UNION ALL
  SELECT 'acl_columnas_resto', obj || '|' || grantor || '|' || grantee || '|' || priv
  FROM col_rows
  WHERE NOT (grantee = 'service_role' AND rel IN ('public.question_keys', 'public.question_assets'))
  UNION ALL
  SELECT 'estructura', s || '.' || n || '|' || relkind::text || '|' || pg_get_userbyid(relowner) || '|' || rls || '|' || frls
  FROM app_rel
  UNION ALL
  SELECT 'estructura', 'fn|' || fn || '|' || owner || '|' || prosecdef || '|' || config || '|' || acl FROM fn_rows
  UNION ALL
  SELECT 'estructura', 'trg|' || trg || '|' || enabled FROM trg_rows
  UNION ALL
  SELECT 'estructura', 'pol|' || pol || '|' || what FROM pol_rows
  UNION ALL
  SELECT 'estructura', 'ns|' || s || '|' || owner || '|' || acl FROM ns_rows
  UNION ALL
  SELECT 'efectivos_resto', role || '|' || obj || '|' || privs FROM eff
  WHERE NOT (role = 'service_role' AND obj IN ('public.question_keys', 'public.question_assets'))
  UNION ALL
  SELECT 'efectivos_resto', 'col|' || role || '|' || obj || '|' || privs FROM eff_col
  WHERE role <> 'service_role'
  UNION ALL
  SELECT k, '' FROM (VALUES ('acl_resto'), ('acl_columnas_resto'), ('estructura'), ('efectivos_resto')) AS s(k)
)
SELECT * FROM (
  SELECT 'verificaciones' AS seccion, 'V1 service_role sin privilegios efectivos de tabla (7) en las 2 tablas' AS elemento,
         CASE WHEN (SELECT count(*) FROM app_rel r JOIN secret s ON s.n = r.n AND r.s = 'public'
                    CROSS JOIN privs p WHERE has_table_privilege('service_role', r.oid, p.p)) = 0
              THEN 'PASS' ELSE 'FAIL' END AS valor
  UNION ALL
  SELECT 'verificaciones', 'V2 service_role sin privilegios efectivos de columna en las 2 tablas',
         CASE WHEN (SELECT count(*) FROM app_rel r JOIN secret s ON s.n = r.n AND r.s = 'public'
                    JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum > 0 AND NOT a.attisdropped
                    CROSS JOIN cprivs cp WHERE has_column_privilege('service_role', r.oid, a.attnum, cp.p)) = 0
              THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V3 sin entradas ACL directas de service_role en las 2 tablas (tabla ni columnas)',
         CASE WHEN (SELECT count(*) FROM acl_rows WHERE grantee = 'service_role'
                    AND obj IN ('public.question_keys', 'public.question_assets'))
                 + (SELECT count(*) FROM col_rows WHERE grantee = 'service_role'
                    AND rel IN ('public.question_keys', 'public.question_assets')) = 0
              THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V4 sin entradas de PUBLIC en las 2 tablas',
         CASE WHEN (SELECT count(*) FROM acl_rows WHERE grantee = 'PUBLIC'
                    AND obj IN ('public.question_keys', 'public.question_assets'))
                 + (SELECT count(*) FROM col_rows WHERE grantee = 'PUBLIC'
                    AND rel IN ('public.question_keys', 'public.question_assets')) = 0
              THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V5 sin acceso por herencia: ningun rol (no superusuario, no propietario) que herede de service_role llega a las 2 tablas',
         CASE WHEN (SELECT count(*) FROM secret_access
                    WHERE inherits_service_role AND NOT is_owner AND rolname <> 'service_role') = 0
              THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V6 anon y authenticated sin privilegios efectivos en las 2 tablas',
         CASE WHEN (SELECT count(*) FROM app_rel r JOIN secret s ON s.n = r.n AND r.s = 'public'
                    CROSS JOIN privs p CROSS JOIN (VALUES ('anon'), ('authenticated')) c(role)
                    WHERE has_table_privilege(c.role, r.oid, p.p)) = 0
              THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V7 RLS activada en las 8 tablas esperadas',
         CASE WHEN (SELECT count(*) FROM app_rel r JOIN expected_tables e ON e.n = r.n AND r.s = 'public'
                    WHERE r.rls) = 8 THEN 'PASS' ELSE 'FAIL' END
  UNION ALL
  SELECT 'verificaciones', 'V8 prueba efectiva: el bloque DO previo intento leer las 2 tablas como service_role',
         'PASS (si ves esta fila, el bloque DO no lanzo error: el acceso fue denegado)'
  UNION ALL
  SELECT 'acl_tabla' AS seccion, obj || ' -> ' || grantee AS elemento,
         string_agg(priv, ',' ORDER BY priv) || ' (otorgado por ' || string_agg(DISTINCT grantor, ',') || ')' AS valor
  FROM acl_rows GROUP BY obj, grantee
  UNION ALL
  SELECT 'acl_columna', obj || ' -> ' || grantee, string_agg(priv, ',' ORDER BY priv)
  FROM col_rows GROUP BY obj, grantee
  UNION ALL
  SELECT 'relaciones', s || '.' || n,
         'tipo=' || relkind::text || '; propietario=' || pg_get_userbyid(relowner) || '; rls=' || rls || '; rls_forzada=' || frls
  FROM app_rel
  UNION ALL
  SELECT 'politicas_rls', pol, what FROM pol_rows
  UNION ALL
  SELECT 'politicas_rls', '(recuento total)', count(*)::text FROM pol_rows
  UNION ALL
  SELECT 'triggers', trg, 'enabled=' || enabled FROM trg_rows
  UNION ALL
  SELECT 'funciones', fn, 'propietario=' || owner || '; security_definer=' || prosecdef || '; config=' || config || '; acl=' || acl
  FROM fn_rows
  UNION ALL
  SELECT 'esquemas', s, 'propietario=' || owner || '; acl=' || acl FROM ns_rows
  UNION ALL
  SELECT 'rol_service_role', 'atributos',
         'superuser=' || rolsuper || '; inherit=' || rolinherit || '; login=' || rolcanlogin || '; bypassrls=' || rolbypassrls
  FROM pg_roles WHERE rolname = 'service_role'
  UNION ALL
  SELECT 'membresias', member || ' es miembro de ' || role_name, opts FROM member_rows
  UNION ALL
  SELECT 'privilegios_efectivos', role || ' sobre ' || obj, privs FROM eff
  UNION ALL
  SELECT 'privilegios_columna_efectivos', role || ' sobre ' || obj, privs FROM eff_col
  UNION ALL
  SELECT 'acceso_efectivo_a_secretos', rolname || ' -> public.' || n,
         privs || CASE WHEN is_owner THEN ' (propietario)' ELSE '' END
                || CASE WHEN inherits_service_role THEN ' (hereda de service_role)' ELSE '' END
  FROM secret_access
  UNION ALL
  SELECT 'huellas', k, md5(string_agg(v, ';' ORDER BY v)) || ' (' || count(*) || ' filas)'
  FROM stable_state GROUP BY k
) AS verificacion
ORDER BY seccion, elemento;
