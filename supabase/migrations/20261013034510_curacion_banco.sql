-- CANE MVP: curación del banco de preguntas (2026-10-12). Migración ADITIVA
-- sobre 20261009212148_supabase_cane.sql, que no se modifica.
-- ESTADO: probada solo en PostgreSQL local (PGlite, backend/tests/integration).
-- NO aplicada a pruebas_cane ni al proyecto real.
--
-- Por qué: el importador del banco necesita registrar por qué una pregunta no
-- está activa, de cuál es duplicada y con qué base se verificó su clave.
-- `active` sigue siendo el ÚNICO interruptor del motor de juego; el estado
-- "activa / inactiva / descartada" se deduce de dos columnas:
--   activa     = active
--   descartada = discarded (nunca activa; el rastro evita reimportarla)
--   inactiva   = ninguna de las dos
--
--  questions.discarded       'descartada' (CHECK: no puede estar también activa)
--  questions.review_reason   motivo de no estar activa (sin_clave, grafico_dudoso,
--                            texto_dudoso, duplicada_de, revisar_no_clasificada...)
--  questions.duplicate_of    source_id de la pregunta que se conserva
--  questions.review_note     nota libre (p. ej. avisos de origen de una pregunta
--                            activada a mano)
--  question_keys.verified_basis  con qué base se verificó (p. ej. una decisión en
--                            bloque). verified_by sigue siendo un perfil.
--
-- Sin CHECK que obligue a tener motivo al desactivar: el panel de Supabase edita
-- una celda por vez y esa regla impediría marcar una pregunta como inactiva sin
-- SQL. El importador sí exige el motivo, y docs/importador.md trae una consulta
-- para listar las inactivas sin motivo.
ALTER TABLE public.questions
 ADD COLUMN discarded boolean NOT NULL DEFAULT false,
 ADD COLUMN review_reason text CHECK (review_reason IS NULL OR length(trim(review_reason))>0),
 ADD COLUMN duplicate_of text CHECK (duplicate_of IS NULL OR length(trim(duplicate_of))>0),
 ADD COLUMN review_note text,
 ADD CONSTRAINT questions_discarded_not_active CHECK (NOT (discarded AND active)),
 ADD CONSTRAINT questions_duplicate_of_other CHECK (duplicate_of IS DISTINCT FROM source_id);

ALTER TABLE public.question_keys
 ADD COLUMN verified_basis text CHECK (verified_basis IS NULL OR length(trim(verified_basis))>0);

-- La versión usada en una sesión es inmutable, salvo el estado editorial. Se
-- amplía esa excepción a las columnas nuevas; contenido y clave siguen
-- congelados (hay que crear una revisión nueva). Misma función que en la
-- migración anterior, con una sola diferencia: la lista de columnas excluidas.
CREATE OR REPLACE FUNCTION cane_private.freeze_used_question() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE qid uuid;
BEGIN
 IF TG_TABLE_NAME='questions' THEN
   qid:=OLD.id;
   IF (to_jsonb(NEW)-'active'-'review_status'-'warnings'
       -'discarded'-'review_reason'-'duplicate_of'-'review_note') IS NOT DISTINCT FROM
      (to_jsonb(OLD)-'active'-'review_status'-'warnings'
       -'discarded'-'review_reason'-'duplicate_of'-'review_note') THEN RETURN NEW; END IF;
 ELSE qid:=OLD.question_id; END IF;
 IF EXISTS(SELECT 1 FROM public.session_questions WHERE question_id=qid) THEN
   RAISE EXCEPTION 'Versión usada: cree una revisión nueva';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION cane_private.freeze_used_question() FROM PUBLIC,anon,authenticated;
