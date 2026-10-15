-- CONTROL DE LA CARGA DEL BANCO (solo lectura): ejecutar en el SQL Editor del proyecto REAL
-- (app_cane_prep, referencia lzzyuxploolyqgitjtdu) DESPUES de la carga definitiva. Comprueba
-- nombre y referencia en el panel antes de pegarlo. Tambien sirve ANTES de cargar: todo en 0.
-- Una sola sentencia SELECT: solo recuentos. No devuelve enunciados, opciones, claves de
-- respuesta, bytes de figuras ni datos de personas (correct_option solo se usa como IS [NOT] NULL).
-- Basada en las consultas de control de docs/importador.md. Las cifras "esperado" son las de la
-- curacion aprobada (scripts/curacion_2026-10-12.json); el valor real va primero.

SELECT * FROM (

  SELECT 'preguntas' AS seccion, 'total' AS elemento, count(*) || ' (esperado: 483)' AS valor
  FROM public.questions
  UNION ALL SELECT 'preguntas', 'activas', count(*) FILTER (WHERE active) || ' (esperado: 427)'
  FROM public.questions
  UNION ALL SELECT 'preguntas', 'inactivas (no descartadas)',
         count(*) FILTER (WHERE NOT active AND NOT discarded) || ' (esperado: 55)'
  FROM public.questions
  UNION ALL SELECT 'preguntas', 'descartadas', count(*) FILTER (WHERE discarded) || ' (esperado: 1)'
  FROM public.questions
  UNION ALL SELECT 'preguntas', 'revision distinta de 1', count(*) FILTER (WHERE revision <> 1) || ' (esperado: 0)'
  FROM public.questions
  UNION ALL SELECT 'preguntas', 'bank_id distintos', coalesce(string_agg(DISTINCT bank_id, ', '), '(ninguno)')
  FROM public.questions

  UNION ALL
  SELECT 'por_area', area,
         'activas=' || count(*) FILTER (WHERE active)
         || ' inactivas=' || count(*) FILTER (WHERE NOT active AND NOT discarded)
         || ' descartadas=' || count(*) FILTER (WHERE discarded)
         || ' total=' || count(*)
         || CASE area WHEN 'econometria' THEN ' (esperado 78/19/0, 97)'
                      WHEN 'microeconomia' THEN ' (esperado 124/7/1, 132)'
                      WHEN 'macroeconomia' THEN ' (esperado 108/15/0, 123)'
                      WHEN 'historia_pensamiento' THEN ' (esperado 117/14/0, 131)'
                      ELSE '' END
  FROM public.questions GROUP BY area

  UNION ALL
  SELECT 'microeconomia_63_y_85', 'numero ' || source_number,
         'activa=' || active || '; descartada=' || discarded || ' (esperado: 63 activa, 85 descartada)'
  FROM public.questions WHERE area = 'microeconomia' AND source_number IN (63, 85)

  UNION ALL SELECT 'claves', 'filas en question_keys', count(*) || ' (esperado: 483)' FROM public.question_keys
  UNION ALL SELECT 'claves', 'filas con correct_option no nula',
         count(*) FILTER (WHERE correct_option IS NOT NULL) || ' (esperado: 477; 6 sin clave)'
  FROM public.question_keys
  UNION ALL SELECT 'claves', 'preguntas sin fila en question_keys',
         count(*) || ' (esperado: 0)'
  FROM public.questions q LEFT JOIN public.question_keys k ON k.question_id = q.id
  WHERE k.question_id IS NULL
  UNION ALL SELECT 'claves', 'activas con clave nula o sin verified_at',
         count(*) || ' (esperado: 0)'
  FROM public.questions q JOIN public.question_keys k ON k.question_id = q.id
  WHERE q.active AND (k.correct_option IS NULL OR k.verified_at IS NULL)
  UNION ALL SELECT 'claves', 'activas sin verified_basis',
         count(*) || ' (esperado: 0)'
  FROM public.questions q JOIN public.question_keys k ON k.question_id = q.id
  WHERE q.active AND k.verified_basis IS NULL
  UNION ALL SELECT 'claves', 'no activas con verified_at', count(*) || ' (esperado: 0)'
  FROM public.questions q JOIN public.question_keys k ON k.question_id = q.id
  WHERE NOT q.active AND k.verified_at IS NOT NULL
  UNION ALL SELECT 'claves_verified_basis', coalesce(verified_basis, '(nulo)'), count(*)::text
  FROM public.question_keys GROUP BY verified_basis

  UNION ALL SELECT 'motivos', 'no activas sin review_reason', count(*) || ' (esperado: 0)'
  FROM public.questions WHERE NOT active AND review_reason IS NULL
  UNION ALL
  SELECT 'motivos_por_tipo', review_reason,
         'inactivas=' || count(*) FILTER (WHERE NOT discarded) || ' descartadas=' || count(*) FILTER (WHERE discarded)
  FROM public.questions WHERE NOT active GROUP BY review_reason

  UNION ALL SELECT 'duplicadas', 'con duplicate_of', count(*) || ' (esperado: 15)'
  FROM public.questions WHERE duplicate_of IS NOT NULL

  UNION ALL SELECT 'figuras', 'filas en question_assets', count(*) || ' (esperado: 14)' FROM public.question_assets
  UNION ALL SELECT 'figuras', 'bytes (suma)', coalesce(sum(octet_length(data)), 0) || ' (esperado: 785186)'
  FROM public.question_assets
  UNION ALL SELECT 'figuras', 'preguntas con figura', count(DISTINCT question_id) || ' (esperado: 13)'
  FROM public.question_assets
  UNION ALL SELECT 'figuras', 'de preguntas activas', count(DISTINCT a.question_id) || ' (esperado: 8)'
  FROM public.question_assets a JOIN public.questions q ON q.id = a.question_id WHERE q.active

  UNION ALL SELECT 'juego', 'sesiones', count(*) || ' (esperado ahora: 0)' FROM public.sessions
  UNION ALL SELECT 'juego', 'posiciones de sesion', count(*) || ' (esperado ahora: 0)' FROM public.session_questions
  UNION ALL SELECT 'juego', 'intentos', count(*) || ' (esperado ahora: 0)' FROM public.attempts
  UNION ALL SELECT 'equipos', 'equipos', count(*) || ' (esperado ahora: 0)' FROM public.teams
  UNION ALL SELECT 'equipos', 'perfiles', count(*) || ' (esperado ahora: 0)' FROM public.profiles
  UNION ALL SELECT 'auth', 'cuentas (solo el total)', count(*) || ' (esperado ahora: 0)' FROM auth.users

) AS control
ORDER BY seccion, elemento;
