-- Datos FICTICIOS para probar el backend contra el proyecto de PRUEBAS.
--
-- SOLO para pruebas_cane. NUNCA en el proyecto real de CANE.
-- Requiere: la migración aplicada y un usuario creado en Authentication > Users
-- (con "Auto Confirm User"). Cámbiale el correo en la línea marcada.
--
-- Qué crea (en una sola transacción; si algo falla, no queda nada):
--   - un equipo "Equipo de prueba" y el perfil de ese usuario,
--   - 24 preguntas ficticias (6 por área), activas y con clave verificada.
-- Todas las claves son 'A' y el enunciado lo dice: no es el banco real.
-- Ejecútalo UNA vez; una segunda vez falla por las restricciones de unicidad.

DO $datos$
DECLARE
  v_email text := 'CAMBIA_ESTE_CORREO';   -- <-- el correo del usuario de prueba
  v_user  uuid;
  v_team  uuid;
  v_q     uuid;
  v_area  text;
  i       integer;
  n       integer := 0;
  v_opts  jsonb := '[{"label":"A","text_md":"Opción A"},{"label":"B","text_md":"Opción B"},{"label":"C","text_md":"Opción C"}]';
BEGIN
  SELECT id INTO v_user FROM auth.users WHERE email = v_email;
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'No hay un usuario de Auth con el correo "%". Créalo en Authentication > Users.', v_email;
  END IF;
  IF EXISTS (SELECT 1 FROM public.profiles WHERE id = v_user) THEN
    RAISE EXCEPTION 'Ese usuario ya tiene perfil: no se crea nada.';
  END IF;

  INSERT INTO public.teams(name) VALUES ('Equipo de prueba') RETURNING id INTO v_team;
  INSERT INTO public.profiles(id, team_id, display_name)
  VALUES (v_user, v_team, 'Persona de prueba');

  FOREACH v_area IN ARRAY ARRAY['microeconomia','macroeconomia','econometria','historia_pensamiento'] LOOP
    FOR i IN 1..6 LOOP
      n := n + 1;
      INSERT INTO public.questions(bank_id, source_id, area, source_number, source_pages, statement_md, options)
      VALUES ('prueba-backend', 'pb' || n, v_area, n, ARRAY[1],
              format('**Pregunta ficticia %s** (%s). La respuesta correcta es la opción A.', n, v_area),
              v_opts)
      RETURNING id INTO v_q;
      INSERT INTO public.question_keys(question_id, correct_option, verified_at)
      VALUES (v_q, 'A', now());
      UPDATE public.questions SET review_status = 'ready', active = true WHERE id = v_q;
    END LOOP;
  END LOOP;

  RAISE NOTICE 'Listo: equipo, perfil y % preguntas ficticias.', n;
END;
$datos$;

-- Comprobación (solo lectura):
-- select p.display_name, t.name as equipo from public.profiles p join public.teams t on t.id = p.team_id;
-- select area, count(*) from public.questions where bank_id = 'prueba-backend' and active group by area;

-- LIMPIEZA al terminar las pruebas (descomenta y ejecuta, solo en pruebas_cane).
-- Orden obligatorio: sesiones primero (arrastran manifiestos e intentos), luego
-- preguntas, luego perfil y equipo. El usuario de Auth se borra desde el panel.
--
-- delete from public.sessions where user_id in (select id from public.profiles where display_name = 'Persona de prueba');
-- delete from public.questions where bank_id = 'prueba-backend';
-- delete from public.profiles where display_name = 'Persona de prueba';
-- delete from public.teams where name = 'Equipo de prueba';
