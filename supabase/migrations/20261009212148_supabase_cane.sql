-- CANE MVP, propuesta v1 con las decisiones del 2026-10-09. PostgreSQL/Supabase
-- nuevo. Ejecutar una vez (no es idempotente).
-- ESTADO: probada, NO aplicada al proyecto real. Esta versión se aplicó con la
-- CLI (db push) en el proyecto de pruebas y pasó 14/14 comprobaciones de
-- docs/prueba-migracion.sql (resultado informado por el usuario, 2026-10-11).
-- El SQL ejecutable no cambió después de esa prueba; solo este encabezado.
-- NO contiene cuentas reales ni secretos. Auth gestiona identidades y contraseñas.
-- El frontend solo usa Auth; FastAPI se conecta directo a PostgreSQL con el rol
-- postgres (MVP), con DATABASE_URL solo en el servidor. Ver docs/supabase.md.
-- Ranking, lectura dentro de los 90s y sesiones por fase son decisiones
-- propuestas, no reglas verificadas de la edición 2026.
--
-- Cambios respecto del SQL original (docs/revision-sql-supabase.md):
--  D1  time_limit_seconds fijo en 90 (CHECK = 90).
--  D2  Ranking: precisión DESC y tiempo PROMEDIO por pregunta ASC; sin
--      "aciertos" ni tiempo total como criterio.
--  D5  Una pregunta solo puede estar activa con verified_at en su clave.
--  T1  Sin GRANT a service_role: el backend usa el rol postgres.
--  T4  Sin BEGIN/COMMIT explícitos: la CLI y el SQL Editor ya aplican las
--      sentencias en su propia transacción. Si se ejecuta con otra
--      herramienta (p. ej. psql), envolver el archivo en una transacción.
-- Sin cambio y decididos: D3 primer intento y timeout cuenta como fallo,
-- D4 borrado en cascada, D6 máximo cinco miembros por equipo.
-- Convención (T3): toda tabla nueva lleva ENABLE ROW LEVEL SECURITY y REVOKE a
-- PUBLIC, anon y authenticated en su propia migración.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS cane_private;
REVOKE ALL ON SCHEMA cane_private FROM PUBLIC, anon, authenticated;

CREATE TABLE public.teams (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL CHECK (length(trim(name))>0),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.profiles (
 id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 team_id uuid NOT NULL REFERENCES public.teams(id),
 display_name text NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 80),
 joined_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,team_id)
);
CREATE FUNCTION cane_private.limit_team_size() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 -- Serializar altas por equipo. No confiar en COUNT sin bloqueo.
 PERFORM 1 FROM public.teams WHERE id=NEW.team_id FOR UPDATE;
 IF (SELECT count(*) FROM public.profiles WHERE team_id=NEW.team_id
     AND id<>NEW.id)>=5 THEN
   RAISE EXCEPTION 'El equipo ya tiene cinco miembros';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER profiles_limit BEFORE INSERT OR UPDATE OF team_id ON public.profiles
 FOR EACH ROW EXECUTE FUNCTION cane_private.limit_team_size();

CREATE FUNCTION cane_private.valid_options(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE n integer; e jsonb; k integer:=0;
BEGIN
 IF v IS NULL OR jsonb_typeof(v)<>'array' THEN RETURN false; END IF;
 n:=jsonb_array_length(v);
 IF n NOT BETWEEN 3 AND 5 THEN RETURN false; END IF;
 FOR e IN SELECT value FROM jsonb_array_elements(v) LOOP
   k:=k+1;
   IF jsonb_typeof(e)<>'object' OR e->>'label' IS DISTINCT FROM chr(64+k)
      OR jsonb_typeof(e->'text_md') IS DISTINCT FROM 'string'
      OR length(trim(e->>'text_md'))=0 THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END;
$$;
CREATE FUNCTION cane_private.valid_pages(v integer[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path='' AS $$
 SELECT coalesce(cardinality(v)>0
   AND NOT EXISTS(SELECT 1 FROM unnest(v) AS p WHERE p IS NULL OR p<1)
   AND v=ARRAY(SELECT DISTINCT p FROM unnest(v) AS p ORDER BY p),false);
$$;
CREATE TABLE public.questions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 bank_id text NOT NULL CHECK (length(trim(bank_id))>0),
 source_id text NOT NULL CHECK (length(trim(source_id))>0),
 revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
 area text NOT NULL CHECK (area IN ('microeconomia','macroeconomia','econometria','historia_pensamiento')),
 source_number integer NOT NULL CHECK (source_number>0),
 source_pages integer[] NOT NULL CHECK (cane_private.valid_pages(source_pages)),
 source_year integer CHECK (source_year BETWEEN 1900 AND 2100),
 source_edition text,
 source_phase text CHECK (source_phase IN ('fase_1','fase_2','semifinal','final')),
 statement_md text NOT NULL CHECK (length(trim(statement_md))>0),
 options jsonb NOT NULL CHECK (cane_private.valid_options(options)),
 assets jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(assets)='array'),
 warnings jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(warnings)='array'),
 review_status text NOT NULL DEFAULT 'needs_review' CHECK (review_status IN ('ready','needs_review')),
 active boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(bank_id,source_id,revision),
 UNIQUE(bank_id,area,source_number,revision),
 CHECK (NOT active OR (review_status='ready' AND warnings='[]'::jsonb))
);
-- Separada de contenido visible. No publicar JSONs de importación con esta clave.
CREATE TABLE public.question_keys (
 question_id uuid PRIMARY KEY REFERENCES public.questions(id) ON DELETE CASCADE,
 correct_option text CHECK (correct_option IN ('A','B','C','D','E')),
 verified_at timestamptz,
 verified_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL
);
CREATE INDEX questions_pool ON public.questions(area) WHERE active AND review_status='ready';

CREATE TABLE public.sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL,
 team_id uuid NOT NULL REFERENCES public.teams(id),
 FOREIGN KEY(user_id,team_id) REFERENCES public.profiles(id,team_id) ON DELETE CASCADE,
 mode text NOT NULL CHECK (mode IN ('area','random','simulacro')),
 area_filter text CHECK (area_filter IN ('microeconomia','macroeconomia','econometria','historia_pensamiento')),
 stage text CHECK (stage IN ('fase_1','fase_2','semifinal','final')),
 question_count integer NOT NULL CHECK (question_count>0),
 -- Plazo fijo del MVP (D1): deadline_at y los límites en ms también usan 90.
 time_limit_seconds integer NOT NULL DEFAULT 90 CHECK (time_limit_seconds=90),
 status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned')),
 repeated_from uuid REFERENCES public.sessions(id) ON DELETE SET NULL,
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 CHECK (
  (mode='area' AND area_filter IS NOT NULL AND stage IS NULL) OR
  (mode='random' AND area_filter IS NULL AND stage IS NULL) OR
  (mode='simulacro' AND area_filter IS NULL AND stage IS NOT NULL AND
   question_count=CASE stage WHEN 'fase_1' THEN 16 WHEN 'fase_2' THEN 12
     WHEN 'semifinal' THEN 8 WHEN 'final' THEN 4 END)
 ),
 CHECK ((status='active' AND finished_at IS NULL) OR
        (status IN ('completed','abandoned') AND finished_at IS NOT NULL)),
 CHECK (finished_at IS NULL OR finished_at>=started_at)
);
-- Una fila por pregunta fija el manifiesto; el UUID referencia una versión inmutable.
CREATE TABLE public.session_questions (
 session_id uuid NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
 position integer NOT NULL CHECK (position>0),
 question_id uuid NOT NULL REFERENCES public.questions(id),
 issued_at timestamptz,
 deadline_at timestamptz,
 PRIMARY KEY(session_id,position),
 UNIQUE(session_id,question_id),
 CHECK ((issued_at IS NULL AND deadline_at IS NULL) OR
        (issued_at IS NOT NULL AND deadline_at IS NOT NULL AND deadline_at=issued_at+interval '90 seconds'))
);
CREATE TABLE public.attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 session_id uuid NOT NULL,
 position integer NOT NULL,
 selected_option text CHECK (selected_option IN ('A','B','C','D','E')),
 is_correct boolean NOT NULL,
 timed_out boolean NOT NULL,
 time_used_ms integer NOT NULL CHECK (time_used_ms BETWEEN 0 AND 90000),
 submitted_at timestamptz NOT NULL,
 FOREIGN KEY(session_id,position) REFERENCES public.session_questions(session_id,position) ON DELETE CASCADE,
 UNIQUE(session_id,position),
 CHECK (NOT timed_out OR (selected_option IS NULL AND NOT is_correct AND time_used_ms=90000)),
 CHECK (timed_out OR selected_option IS NOT NULL)
);
CREATE INDEX sessions_person ON public.sessions(user_id,started_at DESC);
CREATE INDEX attempts_session ON public.attempts(session_id);

-- Antes de activar, ambos registros deben estar cargados y la clave debe existir.
-- Trigger diferido: permite importar pregunta+clave en cualquier orden en una transacción.
CREATE FUNCTION cane_private.check_question_key() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE q public.questions%ROWTYPE; k text; v timestamptz; qid uuid;
BEGIN
 IF TG_TABLE_NAME='questions' THEN qid:=coalesce(NEW.id,OLD.id);
 ELSE qid:=coalesce(NEW.question_id,OLD.question_id); END IF;
 SELECT * INTO q FROM public.questions WHERE id=qid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT correct_option,verified_at INTO k,v FROM public.question_keys WHERE question_id=qid;
 IF k IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM jsonb_array_elements(q.options) o WHERE o->>'label'=k) THEN
    RAISE EXCEPTION 'Clave no pertenece a las opciones';
 END IF;
 IF q.review_status='ready' THEN
   IF k IS NULL OR q.warnings<>'[]'::jsonb THEN RAISE EXCEPTION 'Pregunta ready sin clave o con warnings'; END IF;
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(q.assets) a
      WHERE a->>'status' IS DISTINCT FROM 'available') THEN
      RAISE EXCEPTION 'Pregunta ready con asset pendiente';
   END IF;
 END IF;
 -- D5: activar exige que la clave haya sido verificada.
 IF q.active AND v IS NULL THEN
   RAISE EXCEPTION 'Pregunta activa sin verified_at en su clave';
 END IF;
 RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER questions_key_check AFTER INSERT OR UPDATE ON public.questions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cane_private.check_question_key();
CREATE CONSTRAINT TRIGGER keys_question_check AFTER INSERT OR UPDATE OR DELETE ON public.question_keys
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cane_private.check_question_key();

-- No alterar contenido/clave de versiones usadas; crear revision nueva.
CREATE FUNCTION cane_private.freeze_used_question() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE qid uuid;
BEGIN
 IF TG_TABLE_NAME='questions' THEN
   qid:=OLD.id;
   IF (to_jsonb(NEW)-'active'-'review_status'-'warnings') IS NOT DISTINCT FROM
      (to_jsonb(OLD)-'active'-'review_status'-'warnings') THEN RETURN NEW; END IF;
 ELSE qid:=OLD.question_id; END IF;
 IF EXISTS(SELECT 1 FROM public.session_questions WHERE question_id=qid) THEN
   RAISE EXCEPTION 'Versión usada: cree una revisión nueva';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER questions_freeze BEFORE UPDATE ON public.questions
 FOR EACH ROW EXECUTE FUNCTION cane_private.freeze_used_question();
CREATE TRIGGER keys_freeze BEFORE UPDATE OR DELETE ON public.question_keys
 FOR EACH ROW EXECUTE FUNCTION cane_private.freeze_used_question();
-- La API no ofrece DELETE ni UPDATE de intentos/claves históricas.

CREATE FUNCTION cane_private.validate_session_question() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE s public.sessions%ROWTYPE; q public.questions%ROWTYPE;
BEGIN
 SELECT * INTO s FROM public.sessions WHERE id=NEW.session_id FOR UPDATE;
 IF NOT FOUND OR s.status<>'active' THEN RAISE EXCEPTION 'Sesión no activa'; END IF;
 IF TG_OP='UPDATE' THEN
   IF (NEW.session_id,NEW.position,NEW.question_id) IS DISTINCT FROM
      (OLD.session_id,OLD.position,OLD.question_id) THEN RAISE EXCEPTION 'Manifiesto inmutable'; END IF;
   IF OLD.issued_at IS NOT NULL AND (NEW.issued_at,NEW.deadline_at) IS DISTINCT FROM
      (OLD.issued_at,OLD.deadline_at) THEN RAISE EXCEPTION 'Cronómetro ya iniciado'; END IF;
 ELSE
   SELECT * INTO q FROM public.questions WHERE id=NEW.question_id;
   IF NOT FOUND OR NOT q.active OR q.review_status<>'ready' THEN RAISE EXCEPTION 'Pregunta no disponible'; END IF;
   IF s.mode='area' AND q.area<>s.area_filter THEN RAISE EXCEPTION 'Área incorrecta'; END IF;
   IF NEW.position>s.question_count THEN RAISE EXCEPTION 'Posición excede manifiesto'; END IF;
   IF EXISTS(SELECT 1 FROM public.session_questions sq JOIN public.questions oq ON oq.id=sq.question_id
      WHERE sq.session_id=s.id AND oq.bank_id=q.bank_id AND oq.source_id=q.source_id) THEN
      RAISE EXCEPTION 'Misma pregunta con otra revisión en la sesión';
   END IF;
 END IF;
 IF NEW.issued_at IS NOT NULL THEN
   -- No emitir mientras falten preguntas del manifiesto o haya otra sin responder.
   IF (SELECT count(*) FROM public.session_questions WHERE session_id=s.id)<>s.question_count THEN
     RAISE EXCEPTION 'Construya primero todo el manifiesto, luego emita por UPDATE';
   END IF;
   IF EXISTS(SELECT 1 FROM public.session_questions sq WHERE sq.session_id=s.id
       AND sq.position<NEW.position AND NOT EXISTS(SELECT 1 FROM public.attempts a
         WHERE a.session_id=sq.session_id AND a.position=sq.position)) THEN
     RAISE EXCEPTION 'Responda las preguntas anteriores';
   END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER session_questions_guard BEFORE INSERT OR UPDATE ON public.session_questions
 FOR EACH ROW EXECUTE FUNCTION cane_private.validate_session_question();

CREATE FUNCTION cane_private.grade_attempt() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE sq public.session_questions%ROWTYPE; s public.sessions%ROWTYPE; k text; opts jsonb; t timestamptz;
BEGIN
 SELECT * INTO s FROM public.sessions WHERE id=NEW.session_id FOR UPDATE;
 IF NOT FOUND OR s.status<>'active' THEN RAISE EXCEPTION 'Sesión no activa'; END IF;
 SELECT * INTO sq FROM public.session_questions WHERE session_id=NEW.session_id AND position=NEW.position FOR UPDATE;
 IF NOT FOUND OR sq.issued_at IS NULL THEN RAISE EXCEPTION 'Pregunta no emitida'; END IF;
 SELECT correct_option INTO k FROM public.question_keys WHERE question_id=sq.question_id;
 IF k IS NULL THEN RAISE EXCEPTION 'Pregunta sin clave'; END IF;
 SELECT options INTO opts FROM public.questions WHERE id=sq.question_id;
 t:=clock_timestamp();
 IF t<sq.issued_at THEN RAISE EXCEPTION 'Inicio en el futuro'; END IF;
 NEW.submitted_at:=t;
 NEW.timed_out:=t>=sq.deadline_at;
 IF NEW.timed_out THEN
   NEW.selected_option:=NULL; NEW.is_correct:=false; NEW.time_used_ms:=90000;
 ELSE
   IF NEW.selected_option IS NULL OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(opts) o
      WHERE o->>'label'=NEW.selected_option) THEN RAISE EXCEPTION 'Opción inválida'; END IF;
   NEW.is_correct:=NEW.selected_option=k;
   NEW.time_used_ms:=greatest(0,least(90000,floor(extract(epoch FROM (t-sq.issued_at))*1000)::integer));
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER attempts_grade BEFORE INSERT ON public.attempts
 FOR EACH ROW EXECUTE FUNCTION cane_private.grade_attempt();
CREATE FUNCTION cane_private.reject_attempt_update() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN RAISE EXCEPTION 'Intento final: no se puede editar'; END;
$$;
CREATE TRIGGER attempts_immutable BEFORE UPDATE ON public.attempts
 FOR EACH ROW EXECUTE FUNCTION cane_private.reject_attempt_update();

CREATE FUNCTION cane_private.finish_session() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE n integer; per_area integer;
BEGIN
 IF (NEW.user_id,NEW.team_id,NEW.mode,NEW.area_filter,NEW.stage,NEW.question_count,NEW.time_limit_seconds,NEW.started_at)
 IS DISTINCT FROM (OLD.user_id,OLD.team_id,OLD.mode,OLD.area_filter,OLD.stage,OLD.question_count,OLD.time_limit_seconds,OLD.started_at)
 THEN RAISE EXCEPTION 'Configuración de sesión inmutable'; END IF;
 IF OLD.status<>'active' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Sesión cerrada'; END IF;
 IF NEW.status IN ('completed','abandoned') AND OLD.status='active' THEN NEW.finished_at:=clock_timestamp(); END IF;
 IF NEW.status='completed' AND OLD.status='active' THEN
   SELECT count(*) INTO n FROM public.session_questions WHERE session_id=NEW.id;
   IF n<>NEW.question_count OR
     (SELECT count(*) FROM public.attempts WHERE session_id=NEW.id)<>n THEN
     RAISE EXCEPTION 'Manifiesto o intentos incompletos';
   END IF;
   IF (SELECT min(position) FROM public.session_questions WHERE session_id=NEW.id)<>1 OR
      (SELECT max(position) FROM public.session_questions WHERE session_id=NEW.id)<>n THEN
     RAISE EXCEPTION 'Posiciones deben ser consecutivas';
   END IF;
   IF NEW.mode='simulacro' THEN
     per_area:=NEW.question_count/4;
     IF (SELECT count(DISTINCT q.area) FROM public.session_questions sq JOIN public.questions q ON q.id=sq.question_id
         WHERE sq.session_id=NEW.id)<>4 OR EXISTS(
       SELECT 1 FROM public.session_questions sq JOIN public.questions q ON q.id=sq.question_id
       WHERE sq.session_id=NEW.id GROUP BY q.area HAVING count(*)<>per_area) THEN
       RAISE EXCEPTION 'Simulacro exige cupo igual por las cuatro áreas';
     END IF;
   END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER sessions_finish BEFORE UPDATE ON public.sessions
 FOR EACH ROW EXECUTE FUNCTION cane_private.finish_session();

-- RANKING (D2, D3): primera respuesta a cada pregunta fuente en sesión completada.
-- Un timeout cuenta como fallo y como primera respuesta. No hay puntos por repetir.
-- Posición solo después de 20 preguntas distintas.
-- Orden: precisión (% de aciertos) DESC, tiempo PROMEDIO por pregunta ASC.
-- Empates exactos comparten puesto. correct_count se muestra, no desempata.
CREATE VIEW public.practice_ranking WITH (security_invoker=true) AS
WITH first_answers AS (
 SELECT DISTINCT ON (s.user_id,q.bank_id,q.source_id)
 s.user_id,a.is_correct,a.time_used_ms
 FROM public.attempts a JOIN public.sessions s ON s.id=a.session_id
 JOIN public.session_questions sq ON sq.session_id=a.session_id AND sq.position=a.position
 JOIN public.questions q ON q.id=sq.question_id
 WHERE s.status='completed'
 ORDER BY s.user_id,q.bank_id,q.source_id,a.submitted_at,a.id
), totals AS (
 SELECT user_id,count(*) AS questions_seen,
 count(*) FILTER (WHERE is_correct) AS correct_count,
 avg(is_correct::integer::numeric) AS accuracy_ratio,
 avg(time_used_ms::numeric) AS avg_time_ms
 FROM first_answers GROUP BY user_id
), eligible AS (
 SELECT p.team_id,t.user_id,
 rank() OVER (PARTITION BY p.team_id ORDER BY t.accuracy_ratio DESC,t.avg_time_ms ASC) AS rank_position
 FROM totals t JOIN public.profiles p ON p.id=t.user_id WHERE t.questions_seen>=20
), completed AS (
 SELECT user_id,count(*) AS sessions_completed FROM public.sessions WHERE status='completed' GROUP BY user_id
)
SELECT p.team_id,p.id AS user_id,p.display_name,e.rank_position,
 coalesce(t.questions_seen,0) AS questions_seen,coalesce(t.correct_count,0) AS correct_count,
 round(100*t.accuracy_ratio,2) AS accuracy_pct,
 round(t.avg_time_ms/1000,2) AS avg_time_seconds,
 coalesce(c.sessions_completed,0) AS sessions_completed
FROM public.profiles p LEFT JOIN totals t ON t.user_id=p.id
LEFT JOIN eligible e ON e.user_id=p.id LEFT JOIN completed c ON c.user_id=p.id;

-- Arquitectura API-only: cerrar incluso lectura directa de respuestas/intentiones.
ALTER TABLE public.teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.question_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.teams,public.profiles,public.questions,public.question_keys,
 public.sessions,public.session_questions,public.attempts,public.practice_ranking FROM PUBLIC,anon,authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cane_private FROM PUBLIC,anon,authenticated;
-- T1: sin GRANT adicionales. El backend se conecta con el rol postgres (propietario
-- de estos objetos) mediante DATABASE_URL, que solo existe en el servidor.

-- BOOTSTRAP MANUAL (sustituir UUID reales; no ejecutar estos comentarios como están):
-- INSERT INTO public.teams(name) VALUES ('Equipo CANE') RETURNING id;
-- Crear cinco usuarios en Supabase Auth; luego, como administrador:
-- INSERT INTO public.profiles(id,team_id,display_name) VALUES (...);
-- No crear contraseñas ni guardar correo/secretos en estas tablas.

-- Flujo API: validar JWT y perfil; nunca aceptar user_id del cliente como identidad.
-- GET /ranking: SELECT ... FROM practice_ranking WHERE team_id = equipo_del_perfil.
-- POST /sessions: seleccionar últimas revisiones activas y cupos; crear sesión y
-- manifiesto completo en una transacción. La selección/aleatorización vive en FastAPI.
-- POST /sessions/{id}/next: bloquear sesión; emitir una pregunta si no está emitida:
-- UPDATE session_questions SET issued_at=clock_timestamp(),
-- deadline_at=clock_timestamp()+interval '90 seconds' ... NO usar dos clock_timestamp
-- distintos: obtener una sola variable t y usar t / t+90s. No aceptar fecha del navegador.
-- Si ya existe issued_at, devolver ese mismo deadline_at (nunca renovar).
-- POST /answer: validar dueño y posición; insertar solo sesión,posición,selected_option.
-- BEFORE INSERT rellena campos NOT NULL derivados. Unique evita respuestas dobles.
-- Ante conflicto, leer y devolver intento existente; no UPDATE ni reemplazo.
-- Si venció, selected_option NULL es válido y BEFORE INSERT lo convierte en timeout.
-- No emitir la siguiente hasta registrar respuesta/timeout de la actual.
-- Después del último intento: UPDATE sessions SET status='completed' WHERE id=...;
-- Una sesión abandonada no alimenta el ranking. La API necesita un endpoint de abandono.
-- Repetir: nueva sesión + repeated_from y copiar manifiesto; no borrar intentos.
-- Preguntas/clave privadas: jamás SELECT * ni serializar ORM completo a las rutas de juego.
-- Emitir solo statement_md,options,assets,area,posición,deadline_at.
-- Este SQL protege integridad, no reemplaza validación JWT, rate limits o pruebas REST.
