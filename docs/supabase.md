# Supabase: preparación y primera migración

Guía para probar y aplicar la primera migración **con tu autorización en cada
paso remoto**. Nada de CANE Prep se ha aplicado al proyecto real.

## Estado

| Etapa | Estado |
| --- | --- |
| **Preparado localmente** | Contrato de variables de entorno (`.env.example` de frontend y backend), lectura opcional de `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` y `DATABASE_URL` en `backend/app/config.py`. La migración `supabase/migrations/20261009212148_supabase_cane.sql` con las decisiones D1, D2, D5, T1 y T4; los scripts [`prueba-migracion.sql`](prueba-migracion.sql) y [`limpiar-proyecto-pruebas.sql`](limpiar-proyecto-pruebas.sql). |
| **Probado** | La versión actual de la migración se aplicó con la CLI (`db push`, `migration list` con local y remoto coincidiendo) en el proyecto de pruebas `pruebas_cane`, y `prueba-migracion.sql` dio **14/14 `OK`** en el SQL Editor (resultado informado por el usuario, 2026-10-11). Es el mismo archivo que está en el repo (mismo hash SHA-256 que la copia usada en la prueba); después solo cambió el encabezado de comentarios. |
| **Aplicado remotamente** | Proyecto de pruebas: la versión actual. Proyecto real: según las notas y el panel ("No migrations") no hay migraciones; **el contenido real no está inventariado** (ver [`estado-sesion.md`](estado-sesion.md)). |

**Qué cubre la prueba:** RLS y permisos, límite de cinco miembros, plazo fijo
de 90 s, activación con `verified_at`, evaluación por el servidor, doble envío,
timeout, ranking (precisión y luego tiempo **promedio**; distingue promedio de
total), usuario sin 20 preguntas y borrado en cascada. **Qué no cubre:** modos
`area` y `simulacro`, sesiones abandonadas, concurrencia, el acceso real por la
Data API con claves, ni objetos futuros (T3 es solo una convención).

Comprobaciones previas en el proyecto real, de solo lectura, ejecutadas por el
usuario el 2026-10-09: `migration list` sin migraciones locales ni remotas,
`db push --dry-run` sin candidatas y `pg_tables` sin filas en `public` ni
`cane_private`. Eso describe el estado previo a cualquier migración.

El SQL original queda intacto como referencia en
`private-data/supabase_cane.sql` (local, ignorado). Revisión y decisiones:
[`revision-sql-supabase.md`](revision-sql-supabase.md).

## Variables de entorno

| Variable | Dónde | Visibilidad | Uso hoy |
| --- | --- | --- | --- |
| `VITE_API_URL` | frontend | pública | URL del backend: todas las llamadas a la API y `/health` |
| `VITE_SUPABASE_URL` | frontend | pública | Inicio de sesión con Supabase Auth (obligatoria) |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | frontend | pública | Inicio de sesión con Supabase Auth (obligatoria) |
| `FRONTEND_ORIGIN` | backend | configuración | CORS |
| `SUPABASE_URL` | backend | configuración | Validar el token del usuario (`/auth/v1/user`) |
| `SUPABASE_PUBLISHABLE_KEY` | backend | configuración | Cabecera `apikey` de esa llamada |
| `DATABASE_URL` | backend | **secreta** | Acceso a PostgreSQL; `/health` no la usa. Sin ella, las rutas de juego responden 503 |
| `ENABLE_API_DOCS` | backend | configuración | Opcional. Solo con `1`/`true` se publican `/docs`, `/redoc` y `/openapi.json`; por defecto están apagadas |

- Los valores reales van en `frontend/.env` y en el entorno del backend (Render
  más adelante). Ambos están ignorados por Git; solo se versiona `.env.example`.
- Una clave `secret`/`service_role` **no** es un requisito. Si una operación
  concreta la exige, será solo backend y nunca `VITE_*`.
- El backend valida el token y el perfil/equipo en cada petición. Un `user_id`
  recibido del navegador no prueba identidad, y CORS tampoco.

## Nombre de la migración

Generada con `npx supabase migration new supabase_cane`:
`supabase/migrations/20261009212148_supabase_cane.sql`. La versión
`20261009212148` es la fecha y hora UTC de creación (AAAAMMDDHHMMSS) y es la
clave que la CLI registra en el historial remoto. No se renombra tras
aplicarla. Hay tres migraciones, en este orden:

1. `20261009212148_supabase_cane.sql`: el esquema. Probada en `pruebas_cane`
   (14/14).
2. `20261013034510_curacion_banco.sql` (2026-10-12): columnas de curación para
   el importador (`discarded`, `review_reason`, `duplicate_of`, `review_note`,
   `verified_basis`) y el ajuste del congelado de versiones usadas. Es
   **aditiva** y no toca la primera. **Solo probada en PostgreSQL local**
   (PGlite); no se aplicó a `pruebas_cane` ni al real. Para probarla en
   pruebas, mismo método de la carpeta temporal de abajo copiando solo ese
   archivo. **Aplicada a `pruebas_cane` el 2026-10-13** (con la CLI, desde la
   carpeta temporal; `migration list` coincide). Detalle en
   [`importador.md`](importador.md).
3. `20261013044404_question_assets.sql` (2026-10-13): tabla
   `question_assets` (figuras en `bytea`, RLS activado, sin acceso para
   `anon`/`authenticated`, congelada para versiones usadas). **Aplicada a
   `pruebas_cane` el 2026-10-13** (CLI, carpeta temporal; `migration list`
   coincide); no aplicada al real.

## Decisiones adoptadas

| Código | Decisión | En la migración |
| --- | --- | --- |
| D1 | Plazo fijo de 90 s, documentado | `time_limit_seconds` solo admite 90 (`CHECK`); no es configurable en el MVP |
| D2 | Precisión (% de aciertos) y desempate por **tiempo promedio** por pregunta | `ORDER BY accuracy_ratio DESC, avg_time_ms ASC`; sin "aciertos" ni tiempo total como criterio; la vista expone `avg_time_seconds` |
| D3 | Solo el primer intento; un timeout cuenta como fallo | Sin cambio (ya era así) |
| D4 | Borrado en cascada | Sin cambio; probado en T09 (versión anterior) |
| D5 | Activar solo con `verified_at` | `check_question_key` rechaza una pregunta activa sin `verified_at` en su clave |
| D6 | Cinco miembros por equipo | Sin cambio |
| T1 | Rol `postgres` en el MVP, `DATABASE_URL` solo en Render | Se quitaron los 4 `GRANT` a `service_role` |
| T2 | `pgcrypto` quedó en el esquema `extensions` | Cerrado, sin cambio |
| T3 | Permisos de objetos futuros | Sin cambio de SQL. Convención: toda tabla nueva lleva `ENABLE ROW LEVEL SECURITY` y `REVOKE` en su propia migración |
| T4 | Sin `BEGIN`/`COMMIT` explícitos | Quitados; anotado en el encabezado de la migración |
| T5 | `repeated_from` frente a sesiones cerradas | Cerrado: T09 pasó |
| T6 | Índices | Omitido |

Sigue sin confirmar (no cambia el SQL): las reglas de simulacro de 2026 (fases
de 16/12/8/4 basadas en el reglamento de 2025).

**Sobre T4.** Sin `BEGIN`/`COMMIT`, la migración se aplicó con la CLI en el
proyecto de pruebas sin errores y el historial quedó coincidiendo. Eso verifica
que **funciona** en un proyecto vacío. No prueba qué pasa si una sentencia
falla a medias (por eso la guía de aplicación dice no repetir el `push` en ese
caso).

## Probar la migración en el proyecto de pruebas

**Hecho el 2026-10-11** con la versión actual (resultado arriba). Se conserva el
procedimiento por si hay que repetirlo tras cualquier cambio de SQL. Si ya se
aplicó una versión anterior, hay que limpiar primero. Esto se hace **solo en
`pruebas_cane`**.

1. **Limpiar.** Abre [`limpiar-proyecto-pruebas.sql`](limpiar-proyecto-pruebas.sql),
   cambia a mano `false` por `true` en la línea marcada y ejecútalo en el SQL
   Editor de `pruebas_cane`. Comprueba que `pg_tables` queda sin filas en
   `public` y `cane_private`.
2. **Aplicar con la CLI desde una carpeta temporal.** Prueba también T4. No
   uses `supabase link` dentro del repo con el ref de pruebas: cambiaría el
   vínculo y un `push` posterior apuntaría al proyecto equivocado.

   ```powershell
   New-Item -ItemType Directory -Force C:\temp\cane-prueba\supabase\migrations
   Copy-Item supabase\config.toml C:\temp\cane-prueba\supabase\
   Copy-Item supabase\migrations\20261009212148_supabase_cane.sql C:\temp\cane-prueba\supabase\migrations\
   cd C:\temp\cane-prueba
   npx supabase link --project-ref REF_DE_PRUEBAS
   Get-Content supabase\.temp\project-ref      # debe ser el ref de PRUEBAS
   npx supabase db push --dry-run
   npx supabase db push                        # solo aquí, en pruebas
   npx supabase migration list                 # local y remoto coinciden
   ```

   Alternativa sin CLI: pegar la migración en el SQL Editor de `pruebas_cane`.
   Prueba la lógica, pero no cierra T4.
3. **Ejecutar** [`prueba-migracion.sql`](prueba-migracion.sql) en el SQL Editor
   de `pruebas_cane`. Termina con el error deliberado `INFORME DE PRUEBA`, que
   revierte todo. Esperado: todas las líneas `OK`; T08 distingue promedio de
   total.
4. Comparte solo el texto del informe.

Una prueba aprobada permite **proponer** el `db push` al proyecto real; no lo
autoriza.

## Aplicar al proyecto real (guía; no ejecutada)

**No lo ejecutes hasta cumplir las condiciones y autorizarlo por separado.**

### Condiciones previas

- ✔ La versión actual pasó `prueba-migracion.sql` completa y se aplicó con la
  CLI en el proyecto de pruebas (2026-10-11).
- **Volver a comprobar justo antes del `push`:** el proyecto real sigue vacío
  (`pg_tables` sin filas en `public` y `cane_private`) y no se aplicó nada a
  mano ni por la integración de GitHub. No lo deduzcas solo del historial:
  mira el panel.
- **El archivo del repo es el que se probó:** si cambias una sola línea de SQL
  ejecutable, hay que repetir la prueba. Los comentarios no cuentan.
- **Commit antes del `push`**, para que el repositorio refleje exactamente lo
  que se aplica.
- *Automatic branching* y *Deploy to production* de la integración con GitHub
  están desactivados; si estuvieran activos, revisa qué se desplegó antes.
- `supabase/migrations/` contiene solo `.gitkeep` y
  `20261009212148_supabase_cane.sql`, `20261013034510_curacion_banco.sql` y
  `20261013044404_question_assets.sql` (ninguna migración vacía de más).
- ✔ El encabezado de la migración ya refleja que fue probada y que no está
  aplicada al real. Tras el `push` no edites la migración: si algo cambia,
  va en una migración nueva.
- La migración no es idempotente: aplicarla dos veces falla o duplica.
- No hay migración "de vuelta": revertir exigiría una migración nueva. El
  proyecto real está vacío, pero cualquier limpieza la decidimos juntos; no
  se improvisa con `DROP`.

### Pasos

Ejecútalos tú, en la raíz del repo, y revisa la salida de cada uno antes del
siguiente. No pegues contraseñas en el chat ni las pases con `-p`/`--password`.

| # | Comando | Qué hace | Cambia la base |
| --- | --- | --- | --- |
| 1 | `npx supabase login` | Abre el navegador para autenticar la CLI con tu cuenta y guarda un token en tu equipo. Si ya hay sesión, puede omitirse. No uses `--token` con el valor en la línea de comandos. | No |
| 2 | `npx supabase link --project-ref REF_DEL_PROYECTO_REAL` | Asocia la carpeta al proyecto remoto (escribe estado en `supabase/.temp/`, ignorado). Puede pedir la contraseña de la base: solo en la terminal. | No |
| 3 | `Get-Content supabase\.temp\project-ref` | Confirma que el ref vinculado es el real y **no** el de `pruebas_cane`. | No |
| 4 | `npx supabase migration list` | Compara migraciones locales con las del remoto. Esperado: las tres migraciones aparecen como locales, remoto vacío. | No (lectura) |
| 5 | `npx supabase db push --dry-run` | Lista qué se aplicaría, sin aplicarlo. Deben aparecer **solo** `20261009212148_supabase_cane.sql`, `20261013034510_curacion_banco.sql` y `20261013044404_question_assets.sql`, en ese orden. El aviso sobre `.gitkeep` es inofensivo. No prueba que el SQL se ejecute. | No |
| 6 | `npx supabase db push` | **Aplica las migraciones** pendientes al proyecto vinculado y las registra en el historial. Pide confirmación. | **Sí** |

### Qué hacen `link` y `db push --dry-run` (CLI 2.121.0, 2026-10-14)

Verificado con la ayuda local del CLI y con un experimento **solo local** (un PostgreSQL de
PGlite en 127.0.0.1 vía `--db-url`; ningún proyecto remoto):

| Comando | Qué hace | ¿Cambia algo remoto? |
| --- | --- | --- |
| `supabase link --project-ref <ref>` | Asocia la carpeta de trabajo con el proyecto. Escribe estado local en `supabase/.temp/` de **esa** carpeta. Según la documentación, lee y valida la configuración de PostgREST de la plataforma; pide la contraseña de la base solo para validar ajustes y se puede dejar en blanco. Usa el token de `supabase login` | No según la documentación (lecturas) |
| `supabase db push --dry-run` | Se **conecta** a la base ("Connecting to remote database..."), compara con el historial y **imprime** las migraciones que aplicaría, en orden. No ejecuta SQL de las migraciones ni crea `supabase_migrations` ni tablas (comprobado en local) | No aplica nada |
| `supabase db push` | Aplica y registra en `supabase_migrations.schema_migrations` | **Sí** |

- `db push` también actualiza los *vault secrets* de `config.toml` antes de migrar salvo con
  `--skip-vault`. Este repo no define `[db.vault]`; aun así el dry-run se ejecuta con
  `--skip-vault`.
- `--include-seed` y `--include-roles` no se usan (`config.toml` tiene `[db.seed]`
  habilitado: solo entra en juego con `--include-seed`).
- Para no depender del vínculo antiguo de `supabase/.temp/` del repo, usa una carpeta de
  trabajo nueva con `--workdir` (la ayuda indica que se usa tal cual, sin buscar en
  directorios superiores).
- La salida del dry-run, con la terminal interactiva, es texto en la salida de error
  (`Would push these migrations:` con las 3 migraciones) y, sin terminal, un JSON
  (`{"upToDate":false,"dryRun":true,"migrations":[...]}`).
- **Sin verificar** (la documentación no lo dice): si cada migración se aplica en su propia
  transacción y qué pasa si falla la segunda tras aplicar la primera. Por eso la guía manda
  no repetir un `push` fallido sin inspeccionar.

### Cuándo detenerse

Detente y describe el problema, sin improvisar, si en el paso 4 o 5:

- aparecen migraciones desconocidas, tablas preexistentes o un historial
  local/remoto inconsistente;
- el ref del paso 3 no es el esperado;
- el dry-run lista algo distinto de las tres migraciones.

Tampoco uses `migration repair`, `db reset --linked`, `DROP` ni repitas un
`CREATE` para "hacerlo pasar". Si el paso 6 falla a medias, **no lo repitas**:
puede haber quedado un esquema parcial sin registro en el historial. Revisa
`pg_tables` y comparte la salida.

### Después del push

1. `npx supabase migration list`: local y remoto coinciden.
2. Consultas de solo lectura en el SQL Editor del proyecto real:

   ```sql
   -- RLS activado en las tablas del juego (deben ser 7 con rowsecurity = true)
   select tablename, rowsecurity
   from pg_tables where schemaname = 'public';

   -- Permisos directos de los roles del cliente (no debería haber filas)
   select grantee, table_schema, table_name, privilege_type
   from information_schema.role_table_grants
   where grantee in ('anon','authenticated')
     and table_schema in ('public','cane_private');
   ```
3. Opcional: comprobar que la Data API no expone nada (lo ejecutas tú, con la
   clave publicable): una petición a `/rest/v1/question_keys?select=*` debe
   devolver error de permisos o una lista vacía, nunca filas.
4. **No ejecutes `prueba-migracion.sql` en el proyecto real.**

## Lista manual del panel (no se ha cambiado nada)

- **GitHub**: integración opcional. Sin *Automatic branching* ni *Deploy to
  production* en esta fase.
- **Auth**: acceso cerrado para cinco usuarios; verifica que el registro
  abierto esté **desactivado**. Ojo: `supabase/config.toml` tiene
  `enable_signup = true` en `[auth]` y `[auth.email]` (valor por defecto de la
  CLI para la pila local). No lo ejecutes con `supabase config push` sin
  revisarlo. No invites usuarios todavía ni inventes correos/UUID.
- **Site URL y redirects**: usa solo rutas que existan en el frontend. El
  `site_url` local de `config.toml` es `http://127.0.0.1:3000`, distinto del
  puerto de Vite (5173). No definas callbacks ni direcciones de Netlify/Render
  hasta conocerlas.
- **Correos**: comprueba el SMTP y sus límites antes de depender de
  invitaciones o recuperación. No añadas compañeros como administradores del
  proyecto para esto.
- **PostgreSQL**: obtén la cadena en **Connect** (no inventes el host del
  pooler). Verifica qué modo (directa, *session pooler*, *transaction pooler*)
  admite el proveedor del backend (IPv6/IPv4) y tu controlador (el modo
  transacción no admite sentencias preparadas). Usa SSL y transacciones para
  las operaciones atómicas. En el MVP el rol es `postgres`, con la cadena solo
  en Render.
- **Backend**: valida el token de Supabase y el perfil/equipo en cada
  endpoint. El mecanismo concreto (verificación del JWT o consulta a Auth) se
  decide en la parte 3.
- **Datos**: el banco y las claves se importan desde un proceso privado,
  separados y vinculados en una transacción. No uses un `seed.sql` público con
  respuestas ni versiones PDF/JSON con `correct_option`.
