# Supabase: preparación y primera migración

Guía para revisar y ejecutar la primera migración **con tu confirmación en cada
paso remoto**. Nada de lo descrito aquí se ha aplicado a ninguna base remota.

## Estado

| Etapa | Estado |
| --- | --- |
| **Preparado localmente** | Contrato de variables de entorno (`.env.example` de frontend y backend), lectura opcional de `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` y `DATABASE_URL` en `backend/app/config.py`, esta guía. |
| **Probado localmente** | `/health` responde sin credenciales; las variables vacías cuentan como no definidas; `DATABASE_URL` no aparece en `repr`. No se probó ningún SQL: no hay Docker en este equipo y el SQL aún no está en el repo. |
| **Aplicado remotamente** | Nada. |

La migración **no existe todavía** en `supabase/migrations/`. El archivo
`supabase_cane.sql` no estaba disponible al preparar esta parte, así que no se
revisó ni se copió. Hasta entonces, no hay nada que aplicar.

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

## Nombre de la migración (decisión pendiente)

El nombre acordado fue `supabase/migrations/20261009_supabase_cane.sql`.

La CLI instalada (2.120.0) genera nombres con 14 dígitos
(`AAAAMMDDHHMMSS_nombre.sql`). Lo comprobé ejecutando
`npx supabase migration new supabase_cane` en un directorio aislado y temporal:
produjo `20261009204713_supabase_cane.sql`. No lo hice dentro de este repo.

Con 8 dígitos (`20261009`) no pude comprobar cómo lo registra la CLI, porque
hacerlo requiere una base (local con Docker o remota). Por eso **propongo**
generar el archivo con `npx supabase migration new supabase_cane` y pegar el
SQL revisado dentro. Es tu decisión: no se renombra ni se crea nada hasta que
confirmes. El nombre definitivo se genera en ese momento; el de arriba es solo
el resultado de la prueba.

Reglas: una sola migración con ese SQL; el SQL original se conserva fuera de
`migrations/` como referencia local (no como copia ejecutable).

## Revisión del SQL (pendiente)

Cuando esté disponible el archivo, se revisa **el archivo real**, sin
reconstruirlo. Lista de verificación:

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

### Puntos a resolver antes de aplicar

Vienen del resumen del proyecto y **no están verificados contra el archivo**.
No se han cambiado ni convertido en regla definitiva:

- **Cronómetro configurable**: según el resumen, `deadline` y el trigger
  siguen fijos en 90 s; cambiar solo `time_limit_seconds` no basta. Decidir si
  el MVP queda con 90 s fijos documentados o si se adapta el SQL.
- **Regla al vencer el plazo**: qué se registra y cómo cuenta en el ranking.
- **Desempate**: tiempo total o tiempo medio (confirmado solo "tiempo"). El SQL
  propone precisión, aciertos y tiempo medio; "aciertos" no está acordado.
- **Intentos que cuentan**: el SQL propone la primera respuesta por pregunta y
  persona en sesiones completadas, con 20 preguntas distintas.
- **Simulacro**: fases de 16/12/8/4 basadas en el reglamento de 2025; faltan
  las reglas de 2026.

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
