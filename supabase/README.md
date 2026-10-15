# Supabase

Aquí vive el esquema de PostgreSQL de CANE Prep. Hay **cuatro migraciones, ninguna
aplicada al proyecto real**: las tres primeras están aplicadas en el proyecto de
pruebas; la cuarta (`20261014185955_revoke_service_role_secrets.sql`) está solo preparada y probada en local.

## Qué hay hoy

- `config.toml`: configuración local de la CLI de Supabase, generada antes de
  esta parte (commit `a830a30`). No se ha modificado.
- `.gitignore`: generado por la CLI; excluye `.branches`, `.temp` y variantes
  de `.env`.
- `.temp/` y `.branches/`: estado local de la CLI. Están ignorados (también por
  el `.gitignore` de la raíz) y no deben versionarse.
- `migrations/20261009212148_supabase_cane.sql`: esquema inicial (7 tablas,
  vista del ranking, funciones en `cane_private`). Aplicada con la CLI y
  probada (14/14) en un proyecto de pruebas el 2026-10-11. Decisiones y
  cambios: [`docs/supabase.md`](../docs/supabase.md).
- `migrations/20261013034510_curacion_banco.sql`: columnas de curación del
  banco (estado descartada, motivo, duplicada de, base de verificación).
  Aditiva; aplicada a `pruebas_cane` (2026-10-13). Ver
  [`docs/importador.md`](../docs/importador.md).
- `migrations/20261013044404_question_assets.sql`: figuras de las preguntas
  (`question_assets`, bytea) servidas por la API. Aditiva; aplicada a
  `pruebas_cane` (2026-10-13).

## Qué falta

- Aplicarla una sola vez en el proyecto real, con autorización explícita y
  usando la CLI (`db push`), siguiendo la guía de
  [`docs/supabase.md`](../docs/supabase.md). La migración no es idempotente:
  no la repitas en el SQL Editor del proyecto real, y no la edites después de
  aplicarla.
- Configurar Auth, las cinco identidades del equipo y sus perfiles.
- Importar el banco de preguntas desde `private-data/` (contenido y claves por
  separado, en una transacción).

## Reglas

- No guardes en este directorio contraseñas, claves de servicio ni cadenas de
  conexión. Las credenciales privadas van en variables de entorno del backend.
- No versiones PDF resaltados ni JSON con `correct_option` (ni aquí, ni en
  `seed.sql`, ni en `docs/`, ni en `frontend/public/`). El banco vive en
  `private-data/`, que Git no conserva.
- No crees migraciones vacías ni tablas "de ejemplo": una migración
  versionada se considera ejecutable.
