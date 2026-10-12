-- Limpieza del PROYECTO DE PRUEBAS antes de volver a aplicar la migración.
--
-- DESTRUCTIVO. Borra las 7 tablas, la vista y el esquema cane_private creados
-- por supabase/migrations/20261009212148_supabase_cane.sql, con todos sus datos.
-- NUNCA lo ejecutes en el proyecto real de CANE.
--
-- Protección: por defecto no hace nada. Para ejecutarlo, cambia a mano
-- `false` por `true` en la línea marcada, solo después de comprobar en el
-- panel que estás en el proyecto de PRUEBAS (pruebas_cane).
--
-- No toca la extensión pgcrypto ni el esquema auth (usuarios de Auth).

DO $limpieza$
DECLARE
  estoy_en_el_proyecto_de_pruebas boolean := false;   -- <-- cambiar a true
BEGIN
  IF NOT estoy_en_el_proyecto_de_pruebas THEN
    RAISE EXCEPTION 'No se borró nada: confirma que estás en el proyecto de PRUEBAS y cambia el valor a true.';
  END IF;

  DROP VIEW IF EXISTS public.practice_ranking;
  DROP TABLE IF EXISTS public.attempts, public.session_questions, public.sessions,
                       public.question_keys, public.questions,
                       public.profiles, public.teams CASCADE;
  DROP SCHEMA IF EXISTS cane_private CASCADE;

  RAISE NOTICE 'Limpieza completada en el proyecto de pruebas.';
END;
$limpieza$;

-- Comprobación posterior (debe devolver 0 filas):
-- select schemaname, tablename from pg_tables where schemaname in ('public','cane_private');
