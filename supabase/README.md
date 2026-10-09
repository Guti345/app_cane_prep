# Supabase

Aquí vivirá el esquema de PostgreSQL de CANE Prep. **Todavía no hay ninguna
migración**: `migrations/` solo contiene un `.gitkeep` para conservar la
carpeta.

## Qué hay hoy

- `config.toml`: configuración local de la CLI de Supabase, generada antes de
  esta parte (commit `a830a30`). No se ha modificado aquí.
- `.gitignore`: generado por la CLI; excluye `.branches`, `.temp` y variantes
  de `.env`.
- `.temp/` y `.branches/`: estado local de la CLI. Están ignorados (también por
  el `.gitignore` de la raíz) y no deben versionarse.
- `migrations/`: vacía.

## Qué falta

- Revisar el SQL recibido (`supabase_cane.sql`, aún no incluido en el repo) y
  convertirlo en la migración. Tiene decisiones abiertas; ver
  [`docs/supabase.md`](../docs/supabase.md) y
  [`docs/decisiones-pendientes.md`](../docs/decisiones-pendientes.md).
- Aplicarla una sola vez en el proyecto correcto y verificar tablas, permisos
  e historial. Recomendación del plan: usar la CLI (`db push`) y no pegar
  además el SQL en el SQL Editor, porque la migración no es idempotente.
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
