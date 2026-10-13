-- CANE MVP: imágenes de las preguntas (2026-10-13). Migración ADITIVA; no
-- modifica las anteriores.
-- ESTADO: probada solo en PostgreSQL local (PGlite, backend/tests/integration).
-- NO aplicada a pruebas_cane ni al proyecto real.
--
-- Decisión (Antonio, 2026-10-12): las figuras viven en PostgreSQL (bytea) y las
-- sirve un endpoint autenticado de FastAPI; no hay Storage ni URLs públicas.
-- Son ~14 archivos de ~770 KB en total. La clave `ref` es la misma ruta
-- relativa que trae el lote ("assets/<id>-fig-01.png") y que aparece en
-- questions.assets y en el Markdown del enunciado.
--
-- Mismas reglas que el resto de tablas del juego (convención T3): RLS activado
-- y sin acceso para PUBLIC, anon ni authenticated. El backend (rol postgres) es
-- el único que la lee, y solo para preguntas ya emitidas en una sesión propia.
-- Una figura de una versión usada en una sesión es inmutable, igual que su
-- enunciado: reutiliza el trigger de congelado (usa OLD.question_id).
CREATE TABLE public.question_assets (
 question_id uuid NOT NULL REFERENCES public.questions(id) ON DELETE CASCADE,
 ref text NOT NULL CHECK (ref ~ '^assets/[a-z0-9_-]+\.(png|jpg|webp)$'),
 mime_type text NOT NULL CHECK (mime_type IN ('image/png','image/jpeg','image/webp')),
 sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 data bytea NOT NULL CHECK (octet_length(data) BETWEEN 1 AND 2097152),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (question_id, ref)
);
ALTER TABLE public.question_assets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.question_assets FROM PUBLIC, anon, authenticated;
CREATE TRIGGER question_assets_freeze BEFORE UPDATE OR DELETE ON public.question_assets
 FOR EACH ROW EXECUTE FUNCTION cane_private.freeze_used_question();
