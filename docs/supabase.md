# Supabase: preparación y primera migración

Guía para revisar y ejecutar la primera migración **con tu confirmación en cada
paso remoto**. Nada de lo descrito aquí se ha aplicado a ninguna base remota.

## Estado

| Etapa | Estado |
| --- | --- |
| **Preparado localmente** | Contrato de variables de entorno (`.env.example` de frontend y backend), lectura opcional de `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` y `DATABASE_URL` en `backend/app/config.py`, esta guía. La migración `supabase/migrations/20261009212148_supabase_cane.sql` con las decisiones D1, D2, D5 y T1, y el script de prueba [`prueba-migracion.sql`](prueba-migracion.sql). |
| **Probado localmente** | `/health` responde sin credenciales; las variables vacías cuentan como no definidas; `DATABASE_URL` no aparece en `repr`. La migración y el script de prueba pasaron un análisis de sintaxis (pglast), pero **nunca se ejecutaron**: no hay Docker en este equipo. |
| **Aplicado remotamente** | Nada: ni en el proyecto real ni en uno de pruebas. |

Comprobaciones remotas de solo lectura, ejecutadas por el usuario el
2026-10-09 (no por Claude):

- `login` y `link` completados; `migration list` sin migraciones locales ni
  remotas; `db push --dry-run` sin candidatas.
- Consulta a `pg_tables` para `public` y `cane_private`: sin filas, es decir,
  el esquema remoto estaba vacío en ese momento.

Eso describe el estado previo a cualquier migración; no cambia el hecho de que
nada de CANE Prep se ha aplicado todavía.

La migración existe en `supabase/migrations/20261009212148_supabase_cane.sql`
y está **pendiente de revisión y aplicación**: tiene sintaxis válida, pero no
se ha ejecutado en ninguna base. Aparecerá como candidata en `db push` contra
el proyecto vinculado (el real): **no ejecutes `db push` ahí** hasta pasar la
prueba y autorizarlo. El SQL original queda intacto como referencia en
`private-data/supabase_cane.sql` (local, ignorado). Revisión y decisiones:
[`revision-sql-supabase.md`](revision-sql-supabase.md).

## Variables de entorno

| Variable | Dónde | Visibilidad | Uso hoy |
| --- | --- | --- | --- |
| `VITE_API_URL` | frontend | pública | Consulta `/health` |
| `VITE_SUPABASE_URL` | frontend | pública | Ninguno (Auth sin implementar) |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | frontend | pública | Ninguno |
| `FRONTEND_ORIGIN` | backend | privada de configuración | CORS |
| `SUPABASE_URL` | backend | configuración | Ninguno |
| `SUPABASE_PUBLISHABLE_KEY` | backend | configuración | Ninguno |
| `DATABASE_URL` | backend | **secreta** | Ninguno; `/health` no la usa |

- Los valores reales van en `frontend/.env` y en el entorno del backend (Render
  más adelante). Ambos están ignorados por Git; solo se versiona `.env.example`.
- Una clave `secret`/`service_role` **no** es un requisito. Si una operación
  concreta la exige, será solo backend y nunca `VITE_*`.
- Las variables públicas del frontend no sustituyen la autorización del API:
  el backend valida el token y el perfil/equipo en cada petición. Un `user_id`
  recibido del navegador no prueba identidad, y CORS tampoco.

## Nombre de la migración

Decidido: generarlo con `npx supabase migration new supabase_cane`. El archivo
resultante es `supabase/migrations/20261009212148_supabase_cane.sql`: la versión
`20261009212148` es la fecha y hora UTC de creación (AAAAMMDDHHMMSS) y es la
clave que la CLI registra en el historial remoto. No se renombra tras
aplicarla.

Reglas: una sola migración con este SQL; el original se conserva fuera de
`migrations/` como referencia local, no como copia ejecutable.

## Revisión del SQL

Hecha sobre el archivo real; resultados y puntos a decidir en
[`revision-sql-supabase.md`](revision-sql-supabase.md). Lista de verificación
usada:

1. **Contenido**: sin filas del banco, sin `correct_option` concretos, sin
   credenciales ni cuentas reales. Definir `question_keys`/`correct_option`
   como estructura es válido.
2. **Objetos**: siete tablas en `public` (`teams`, `profiles`, `questions`,
   `question_keys`, `sessions`, `session_questions`, `attempts`), la vista
   `practice_ranking` y funciones en `cane_private`. Confirmar que coincide con
   lo propuesto.
3. **RLS y permisos**: RLS activado en cada tabla; `REVOKE` de permisos
   directos a `anon` y `authenticated` (tablas, vista y funciones); sin
   políticas de lectura pública; `question_keys` inaccesible desde el cliente.
   Comprobar también permisos por defecto sobre objetos futuros y que las
   funciones `SECURITY DEFINER` fijen `search_path`.
4. **Integridad**: claves foráneas, restricciones únicas contra doble envío,
   triggers, transacciones y coherencia entre plazo, estado y respuestas.
5. **Cronómetro**: localizar cada valor fijo de 90 segundos (`deadline`,
   `timeout`, límites en milisegundos, trigger).
6. **Ranking**: mínimo de 20 preguntas, desempates y conjunto de intentos.

### Decisiones adoptadas (2026-10-09)

| Código | Decisión | En la migración |
| --- | --- | --- |
| D1 | Plazo fijo de 90 s, documentado | `time_limit_seconds` solo admite 90 (`CHECK`); no es configurable en el MVP |
| D2 | Precisión (% de aciertos) y desempate por tiempo total | `ORDER BY accuracy_ratio DESC, total_time_ms ASC`; la columna `total_time_seconds` es nueva |
| D3 | Solo el primer intento; un timeout cuenta como fallo | Sin cambio (ya era así) |
| D4 | Borrado en cascada | Sin cambio |
| D5 | Activar solo con `verified_at` | `check_question_key` rechaza una pregunta activa sin `verified_at` en su clave |
| D6 | Cinco miembros por equipo | Sin cambio |
| T1 | Rol `postgres` en el MVP, `DATABASE_URL` solo en Render | Se quitaron los 4 `GRANT` a `service_role` |

Sigue sin confirmar (no cambia el SQL): las reglas de simulacro de 2026 (fases
de 16/12/8/4 basadas en el reglamento de 2025). Los puntos técnicos T2-T6 de
[`revision-sql-supabase.md`](revision-sql-supabase.md) **no se aplicaron**; se
decidirán con el resultado de la prueba.

## Probar en un proyecto desechable

Antes de tocar el proyecto real, la migración se prueba en un proyecto
Supabase **nuevo y vacío, creado solo para pruebas**. Nada de esto está hecho.

**Cuidado con el vínculo.** `supabase link` cambia el proyecto asociado a la
carpeta. Si lo ejecutas dentro del repo con el ref de pruebas, un `db push`
posterior apuntaría al proyecto equivocado. Por eso hay dos caminos que no lo
tocan.

**Opción A (recomendada, la más simple): SQL Editor del proyecto de pruebas.**

1. Abre el SQL Editor del proyecto **de pruebas** y pega el contenido de
   `supabase/migrations/20261009212148_supabase_cane.sql`. Ejecútalo una vez.
2. En otra pestaña, pega [`prueba-migracion.sql`](prueba-migracion.sql) y
   ejecútalo. Termina con un error deliberado `INFORME DE PRUEBA` que revierte
   todo y lista cada comprobación como `OK` o `FALLA`.

Esta opción prueba el SQL y la lógica; no prueba cómo lo trata la CLI (por
ejemplo, el `BEGIN`/`COMMIT` interno, punto T4).

**Opción B: la CLI desde una carpeta temporal.**

```powershell
New-Item -ItemType Directory -Force C:\temp\cane-prueba\supabase\migrations
Copy-Item supabase\config.toml C:\temp\cane-prueba\supabase\
Copy-Item supabase\migrations\20261009212148_supabase_cane.sql C:\temp\cane-prueba\supabase\migrations\
cd C:\temp\cane-prueba
npx supabase link --project-ref REF_DEL_PROYECTO_DE_PRUEBAS
Get-Content supabase\.temp\project-ref      # confirma que es el ref de PRUEBAS
npx supabase db push --dry-run
npx supabase db push                        # solo aquí, en el proyecto de pruebas
npx supabase migration list
```

Luego ejecuta `prueba-migracion.sql` en el SQL Editor de ese proyecto.

Al terminar, comparte solo el texto del informe. Una prueba aprobada permite
**proponer** el `db push` al proyecto real; no lo autoriza. Esa autorización
sigue siendo explícita y se da sobre el proyecto y los cambios revisados.

## Pasos remotos (guiados; los ejecutas tú)

Ejecuta cada comando en tu terminal, en la raíz del repo, y revisa la salida
antes del siguiente. No los pegues con contraseñas en el chat ni en scripts.

```powershell
npx supabase login
npx supabase link --project-ref TU_PROJECT_REF
npx supabase migration list
npx supabase db push --dry-run
```

| Comando | Qué hace | Cambia la base |
| --- | --- | --- |
| `npx supabase login` | Abre el navegador para autenticar la CLI con tu cuenta y guarda un token de acceso en tu equipo. Si no puedes abrir navegador, existe `--no-browser`. No uses `--token` con el valor en la línea de comandos. | No |
| `npx supabase link --project-ref TU_PROJECT_REF` | Asocia esta carpeta a un proyecto remoto y escribe estado local en `supabase/.temp/` (ignorado). Puede pedir la contraseña de la base: escríbela **solo en la terminal**; evita `--password`/`-p`, que queda en el historial. | No |
| `npx supabase migration list` | Compara las migraciones locales con las registradas en el remoto (`supabase_migrations.schema_migrations`). | No (lectura) |
| `npx supabase db push --dry-run` | Imprime qué migraciones se aplicarían, sin aplicarlas. | No |

Notas:

- El **project ref** son 20 letras minúsculas (panel > Project Settings >
  General, o la URL del panel). No es una clave API. Verifica que coincide con
  el proyecto de CANE antes de continuar.
- En esta carpeta ya existe `supabase/.temp/`, lo que indica que `link` se
  ejecutó antes. No he leído su contenido ni consultado el remoto. Si el ref
  que vas a usar es distinto del vinculado, **no** lo cambies por deducción:
  confírmalo primero.
- `--dry-run` solo lista candidatas; **no prueba que el SQL se ejecute**.
- No uses `--include-seed`, `--include-roles` ni `--include-all` sin
  entender qué añaden. No existe `seed.sql` público y no debe crearse con
  respuestas.
- `db push` actualiza antes los secretos de Vault definidos en `config.toml`;
  hoy esa sección está comentada, así que no hay nada que actualizar.

### Cuándo detenerse

Si `migration list` o `--dry-run` muestran migraciones desconocidas, tablas
preexistentes (`public.teams`, etc., o el esquema `cane_private`) o un
historial local/remoto inconsistente: **para y descríbelo**. No uses
`migration repair`, `db reset --linked`, `DROP` ni repitas un `CREATE` para
"hacerlo pasar".

### Antes de proponer `db push`

- Comprobar si el SQL ya se aplicó a mano (SQL Editor) o por la integración
  con GitHub: mirar en el panel las tablas existentes y los despliegues. No
  deducirlo solo del historial.
- Esta migración **no es idempotente**: aplicarla dos veces falla o duplica.
- Confirmar el proyecto destino y los cambios revisados por escrito.

### Después de un `db push` autorizado (no ejecutado)

1. `npx supabase migration list`: local y remoto deben coincidir.
2. Revisar el esquema resultante. Consultas de solo lectura sugeridas:

```sql
-- RLS activado en las tablas del juego
select schemaname, tablename, rowsecurity
from pg_tables where schemaname in ('public','cane_private');

-- Permisos directos de los roles del cliente (no debería haber)
select grantee, table_schema, table_name, privilege_type
from information_schema.role_table_grants
where grantee in ('anon','authenticated')
  and table_schema in ('public','cane_private');
```

## Lista manual del panel (no se ha cambiado nada)

- **GitHub**: integración opcional. Sin *Automatic branching* ni *Deploy to
  production* en esta fase. Si ya estuvieran activos, revisa qué se desplegó
  antes de aplicar cualquier migración.
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
  transacción no admite sentencias preparadas). Usa SSL y un rol con
  privilegios acotados, y transacciones para las operaciones atómicas.
- **Backend**: valida el token de Supabase y el perfil/equipo en cada
  endpoint. El mecanismo concreto (verificación del JWT o consulta a Auth) se
  decide en la parte 3.
- **Datos**: el banco y las claves se importan desde un proceso privado,
  separados y vinculados en una transacción. No uses un `seed.sql` público con
  respuestas ni versiones PDF/JSON con `correct_option`.

## Qué no se hace en esta parte

Login, administración de usuarios, importación, endpoints de juego, conexión
real a Supabase, `db push`. Siguiente paso, tras tu revisión: primera conexión
real y recorrido completo de una pregunta.
