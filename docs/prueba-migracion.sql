-- Prueba de la migración supabase/migrations/20261009212148_supabase_cane.sql
--
-- SOLO para un proyecto Supabase NUEVO Y VACÍO creado para pruebas.
-- NUNCA en el proyecto real de CANE. Requiere la migración ya aplicada allí.
--
-- No deja datos: termina con un error deliberado ("INFORME DE PRUEBA") que
-- revierte todo y muestra el resultado de cada comprobación. Un error distinto
-- al final significa que la preparación falló: léelo antes de seguir.
-- Los datos son ficticios (preguntas y claves inventadas para la prueba).
-- Este script no se ha ejecutado todavía.

DO $test$
DECLARE
  res text := '';
  v_team uuid;
  v_users uuid[] := ARRAY[]::uuid[];
  v_u uuid;
  v_q uuid;
  v_qs uuid[] := ARRAY[]::uuid[];
  v_s uuid;
  v_s_u2 uuid;
  v_t timestamptz;
  v_ages integer[] := ARRAY[1,10,1];   -- segundos usados por pregunta (usuarios 1..3)
  v_wrong integer[] := ARRAY[0,0,1];   -- preguntas falladas (usuarios 1..3)
  v_opts jsonb := '[{"label":"A","text_md":"a"},{"label":"B","text_md":"b"},{"label":"C","text_md":"c"}]';
  a public.attempts%ROWTYPE;
  r text;
  tb text;
  i integer;
  p integer;
  n integer;
BEGIN
  -- Los triggers diferidos se evalúan al instante para poder probarlos aquí.
  SET CONSTRAINTS ALL IMMEDIATE;

  -- ---------------------------------------------------------------- preparación
  INSERT INTO public.teams(name) VALUES ('Equipo de prueba') RETURNING id INTO v_team;
  FOR i IN 1..6 LOOP
    v_u := gen_random_uuid();
    INSERT INTO auth.users(id) VALUES (v_u);
    v_users := v_users || v_u;
  END LOOP;

  -- ------------------------------------------------- T01 RLS en las 7 tablas
  SELECT count(*) INTO n
  FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
  WHERE ns.nspname = 'public' AND c.relrowsecurity
    AND c.relname IN ('teams','profiles','questions','question_keys','sessions','session_questions','attempts');
  res := res || CASE WHEN n = 7 THEN 'OK    ' ELSE 'FALLA ' END
      || format('T01 RLS activado en las 7 tablas (%s/7)', n) || E'\n';

  -- --------------------------------- T02 anon/authenticated sin permisos directos
  n := 0;
  FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
    FOREACH tb IN ARRAY ARRAY['teams','profiles','questions','question_keys','sessions',
                              'session_questions','attempts','practice_ranking'] LOOP
      IF has_table_privilege(r, 'public.' || tb,
           'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
        n := n + 1;
      END IF;
    END LOOP;
    IF has_schema_privilege(r, 'cane_private', 'USAGE') THEN n := n + 1; END IF;
  END LOOP;
  res := res || CASE WHEN n = 0 THEN 'OK    ' ELSE 'FALLA ' END
      || format('T02 anon/authenticated sin permisos sobre tablas, vista ni cane_private (%s con acceso)', n) || E'\n';

  -- ------------------------------------------------------ T03 máximo 5 miembros
  FOR i IN 1..5 LOOP
    INSERT INTO public.profiles(id, team_id, display_name)
    VALUES (v_users[i], v_team, 'Integrante ' || i);
  END LOOP;
  BEGIN
    INSERT INTO public.profiles(id, team_id, display_name)
    VALUES (v_users[6], v_team, 'Sexto integrante');
    res := res || 'FALLA T03 el sexto miembro fue aceptado' || E'\n';
  EXCEPTION WHEN raise_exception THEN
    res := res || 'OK    T03 el sexto miembro fue rechazado' || E'\n';
  END;

  -- ----------------------------------------------- T04 D1: plazo fijo en 90 s
  BEGIN
    INSERT INTO public.sessions(user_id, team_id, mode, question_count, time_limit_seconds)
    VALUES (v_users[4], v_team, 'random', 1, 60);
    res := res || 'FALLA T04 se aceptó time_limit_seconds = 60' || E'\n';
  EXCEPTION WHEN check_violation THEN
    res := res || 'OK    T04 time_limit_seconds distinto de 90 rechazado' || E'\n';
  END;

  -- ------------------------------------- T05 D5: activar exige verified_at
  INSERT INTO public.questions(bank_id, source_id, area, source_number, source_pages, statement_md, options)
  VALUES ('prueba', 'p0', 'microeconomia', 1, ARRAY[1], 'Enunciado ficticio', v_opts)
  RETURNING id INTO v_q;
  INSERT INTO public.question_keys(question_id, correct_option) VALUES (v_q, 'A');  -- sin verified_at
  BEGIN
    UPDATE public.questions SET review_status = 'ready', active = true WHERE id = v_q;
    res := res || 'FALLA T05 se activó una pregunta sin verified_at' || E'\n';
  EXCEPTION WHEN raise_exception THEN
    res := res || 'OK    T05 activar sin verified_at fue rechazado' || E'\n';
  END;
  UPDATE public.question_keys SET verified_at = now() WHERE question_id = v_q;
  BEGIN
    UPDATE public.questions SET review_status = 'ready', active = true WHERE id = v_q;
    res := res || 'OK    T05 activar con verified_at fue aceptado' || E'\n';
  EXCEPTION WHEN OTHERS THEN
    res := res || 'FALLA T05 activar con verified_at: ' || SQLERRM || E'\n';
  END;

  -- ----------------- T06 acierto, tiempo medido por el servidor y doble envío
  INSERT INTO public.sessions(user_id, team_id, mode, question_count)
  VALUES (v_users[4], v_team, 'random', 1) RETURNING id INTO v_s;
  INSERT INTO public.session_questions(session_id, position, question_id) VALUES (v_s, 1, v_q);
  v_t := clock_timestamp();
  UPDATE public.session_questions
     SET issued_at = v_t, deadline_at = v_t + interval '90 seconds'
   WHERE session_id = v_s AND position = 1;
  INSERT INTO public.attempts(session_id, position, selected_option) VALUES (v_s, 1, 'A');
  SELECT * INTO a FROM public.attempts WHERE session_id = v_s AND position = 1;
  res := res || CASE WHEN a.is_correct AND NOT a.timed_out THEN 'OK    ' ELSE 'FALLA ' END
      || format('T06 respuesta correcta evaluada por el servidor (is_correct=%s, timed_out=%s, %s ms)',
                a.is_correct, a.timed_out, a.time_used_ms) || E'\n';
  BEGIN
    INSERT INTO public.attempts(session_id, position, selected_option) VALUES (v_s, 1, 'B');
    res := res || 'FALLA T06 se aceptó una segunda respuesta' || E'\n';
  EXCEPTION WHEN unique_violation THEN
    res := res || 'OK    T06 la segunda respuesta fue rechazada' || E'\n';
  END;

  -- ------------------------------ T07 timeout: cuenta como fallo, sin opción
  INSERT INTO public.sessions(user_id, team_id, mode, question_count)
  VALUES (v_users[4], v_team, 'random', 1) RETURNING id INTO v_s;
  INSERT INTO public.session_questions(session_id, position, question_id) VALUES (v_s, 1, v_q);
  v_t := clock_timestamp() - interval '200 seconds';   -- plazo ya vencido
  UPDATE public.session_questions
     SET issued_at = v_t, deadline_at = v_t + interval '90 seconds'
   WHERE session_id = v_s AND position = 1;
  INSERT INTO public.attempts(session_id, position, selected_option) VALUES (v_s, 1, 'A');
  SELECT * INTO a FROM public.attempts WHERE session_id = v_s AND position = 1;
  res := res || CASE WHEN a.timed_out AND NOT a.is_correct AND a.selected_option IS NULL
                      AND a.time_used_ms = 90000 THEN 'OK    ' ELSE 'FALLA ' END
      || format('T07 respuesta tardía = timeout (timed_out=%s, is_correct=%s, opción=%s, %s ms)',
                a.timed_out, a.is_correct, coalesce(a.selected_option, 'NULL'), a.time_used_ms) || E'\n';

  -- ---------------- T08 ranking: precisión primero, luego tiempo total
  FOR i IN 1..20 LOOP
    INSERT INTO public.questions(bank_id, source_id, area, source_number, source_pages, statement_md, options)
    VALUES ('prueba', 'r' || i, 'macroeconomia', i, ARRAY[1], 'Enunciado ficticio ' || i, v_opts)
    RETURNING id INTO v_q;
    INSERT INTO public.question_keys(question_id, correct_option, verified_at) VALUES (v_q, 'A', now());
    UPDATE public.questions SET review_status = 'ready', active = true WHERE id = v_q;
    v_qs := v_qs || v_q;
  END LOOP;

  FOR i IN 1..3 LOOP
    INSERT INTO public.sessions(user_id, team_id, mode, question_count)
    VALUES (v_users[i], v_team, 'random', 20) RETURNING id INTO v_s;
    IF i = 2 THEN v_s_u2 := v_s; END IF;
    FOR p IN 1..20 LOOP
      INSERT INTO public.session_questions(session_id, position, question_id) VALUES (v_s, p, v_qs[p]);
    END LOOP;
    FOR p IN 1..20 LOOP
      v_t := clock_timestamp() - make_interval(secs => v_ages[i]);
      UPDATE public.session_questions
         SET issued_at = v_t, deadline_at = v_t + interval '90 seconds'
       WHERE session_id = v_s AND position = p;
      INSERT INTO public.attempts(session_id, position, selected_option)
      VALUES (v_s, p, CASE WHEN p <= v_wrong[i] THEN 'B' ELSE 'A' END);
    END LOOP;
    UPDATE public.sessions SET status = 'completed' WHERE id = v_s;
  END LOOP;

  -- Esperado: usuario 1 (100 %, ~20 s) = 1; usuario 2 (100 %, ~200 s) = 2;
  -- usuario 3 (95 %, ~20 s) = 3, aunque sea más rápido que el 2.
  FOR i IN 1..3 LOOP
    SELECT rank_position INTO n FROM public.practice_ranking WHERE user_id = v_users[i];
    res := res || CASE WHEN n = i THEN 'OK    ' ELSE 'FALLA ' END
        || format('T08 usuario %s: puesto %s (esperado %s)', i, coalesce(n::text, 'NULL'), i) || E'\n';
  END LOOP;
  SELECT rank_position INTO n FROM public.practice_ranking WHERE user_id = v_users[4];
  res := res || CASE WHEN n IS NULL THEN 'OK    ' ELSE 'FALLA ' END
      || 'T08 usuario 4 (sin 20 preguntas completadas) no tiene puesto' || E'\n';

  -- ------------------------------- T09 D4: borrar un usuario borra su historial
  INSERT INTO public.sessions(user_id, team_id, mode, question_count, repeated_from)
  VALUES (v_users[2], v_team, 'random', 20, v_s_u2);   -- repite la sesión del usuario 2
  BEGIN
    DELETE FROM auth.users WHERE id = v_users[2];
    SELECT count(*) INTO n FROM public.sessions WHERE user_id = v_users[2];
    res := res || CASE WHEN n = 0 THEN 'OK    ' ELSE 'FALLA ' END
        || format('T09 borrar usuario con sesiones repetidas: sesiones restantes = %s', n) || E'\n';
  EXCEPTION WHEN OTHERS THEN
    res := res || 'FALLA T09 no se pudo borrar el usuario (ver T5 en revision-sql-supabase.md): '
        || SQLERRM || E'\n';
  END;

  RAISE EXCEPTION E'INFORME DE PRUEBA (todo se revierte, no queda ningún dato):\n%', res;
END;
$test$;
