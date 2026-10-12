# Probar el backend contra `pruebas_cane`

Guía para correr el backend **en tu equipo** apuntando al proyecto de pruebas
`pruebas_cane`, con un usuario real de Supabase Auth. Nada de esto toca el
proyecto real de CANE ni se despliega.

## Qué prueba y qué no

| Prueba | Qué valida |
| --- | --- |
| Sí | La llamada real a `/auth/v1/user`, el perfil de equipo, la conexión PostgreSQL con SSL y el pooler, el recorrido sesión → pregunta → respuesta → ranking y los timeouts. |
| No | Concurrencia seria, Render, Netlify, el navegador ni el frontend (aún no existe). |

## Estado de esta guía

Los comandos de los pasos 6.1 a 6.5 (incluida la espera real de 95 s) se
ejecutaron con éxito en PowerShell 5.1 contra **el mismo backend** con
PostgreSQL local y un Auth falso, y el script de datos se ejecutó contra la
migración real en local. **No se ha corrido contra `pruebas_cane`**: ese es el
propósito de esta guía. Las diferencias previsibles están en "Problemas
frecuentes".

## Reglas de seguridad

- **Solo `pruebas_cane`.** Las variables incluyen un control que se niega a
  continuar si la URL o la cadena de conexión no contienen el ref de pruebas.
- **Nada de claves en el chat.** Los valores se escriben en la terminal con
  `Read-Host`; viven solo en esa sesión de PowerShell y no se guardan en
  archivos. Cuando termines, cierra la terminal.
- No crees un archivo `.env` con estos valores en el repo.
- Cuando me reportes resultados, comparte **solo códigos de estado y mensajes**,
  nunca tokens, contraseñas ni la cadena de conexión.

## Paso 1: crear el usuario (panel de `pruebas_cane`)

1. **Authentication > Users > Add user > Create new user**.
2. Escribe un correo tuyo de pruebas y una contraseña. Marca **Auto Confirm
   User** (si no, el inicio de sesión exigirá confirmar el correo).
3. La contraseña solo la escribes en el panel; no la compartas.

## Paso 2: equipo, perfil y preguntas ficticias (SQL Editor)

1. Abre el SQL Editor **de `pruebas_cane`** (comprueba el nombre del proyecto
   arriba a la izquierda).
2. Pega [`prueba-backend-datos.sql`](prueba-backend-datos.sql), cambia
   `CAMBIA_ESTE_CORREO` por el correo del paso 1 y ejecútalo **una vez**.
3. Comprueba con:

   ```sql
   select p.display_name, t.name as equipo
   from public.profiles p join public.teams t on t.id = p.team_id;

   select area, count(*) from public.questions
   where bank_id = 'prueba-backend' and active group by area;
   ```

   Deben salir tu perfil en "Equipo de prueba" y 6 preguntas por área.

Qué hace el script: crea el equipo, el perfil de ese usuario y 24 preguntas
**ficticias** (la correcta es siempre `A` y el enunciado lo dice). No toca el
banco real. Si algo falla, no queda nada a medias.

## Paso 3: variables de entorno (Terminal 1)

Dónde sacar cada valor, en el panel de `pruebas_cane`:

| Variable | Dónde |
| --- | --- |
| `SUPABASE_URL` | **Project Settings > API > Project URL** |
| `SUPABASE_PUBLISHABLE_KEY` | **Project Settings > API**: clave *publishable* (no la *secret*) |
| `DATABASE_URL` | Botón **Connect** > cadena de conexión. Sustituye `[YOUR-PASSWORD]` por la contraseña de la base (ver nota) |

Abre una terminal PowerShell en la raíz del repo y ejecuta:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1

$refPruebas = Read-Host "Ref del proyecto pruebas_cane (20 letras)"
$env:SUPABASE_URL = Read-Host "SUPABASE_URL"
$env:SUPABASE_PUBLISHABLE_KEY = Read-Host "SUPABASE_PUBLISHABLE_KEY"
$sec = Read-Host "DATABASE_URL" -AsSecureString
$env:DATABASE_URL = [Net.NetworkCredential]::new('', $sec).Password
$sec = $null

# Control: ambas deben pertenecer al proyecto de pruebas
if ($env:SUPABASE_URL -notlike "*$refPruebas*" -or $env:DATABASE_URL -notlike "*$refPruebas*") {
  Remove-Item Env:SUPABASE_URL, Env:SUPABASE_PUBLISHABLE_KEY, Env:DATABASE_URL
  throw "SUPABASE_URL o DATABASE_URL no contienen el ref de pruebas. Variables borradas. Detente."
}
"Variables cargadas para el proyecto $refPruebas"
```

Notas sobre `DATABASE_URL`:

- La contraseña de la base es la que definiste al crear el proyecto (se
  restablece en **Project Settings > Database**). Si contiene caracteres como
  `@`, `/` o `#`, hay que codificarla en la URL (`%40`, `%2F`, `%23`).
- Si la conexión directa falla (tu red puede no tener IPv6), usa en **Connect**
  la opción **Session pooler**.
- El backend añade `sslmode=require` si la cadena no lo trae, y no usa
  sentencias preparadas.

## Paso 4: arrancar el backend (Terminal 1)

```powershell
uvicorn app.main:app --port 8000
```

Déjala abierta. Con las variables cargadas, el backend arranca sin conectarse:
el pool abre en segundo plano y los fallos de conexión salen como 503 al hacer
peticiones, no al arrancar.

## Paso 5: obtener un token (Terminal 2)

Abre **otra** terminal PowerShell (no cierres la 1):

```powershell
$global:api = "http://localhost:8000"
$supabaseUrl = Read-Host "SUPABASE_URL de pruebas_cane"
$key = Read-Host "SUPABASE_PUBLISHABLE_KEY"
$email = Read-Host "Correo del usuario de prueba"
$pwd = Read-Host "Contraseña" -AsSecureString

$body = @{ email = $email; password = [Net.NetworkCredential]::new('', $pwd).Password } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri "$supabaseUrl/auth/v1/token?grant_type=password" `
       -Headers @{ apikey = $key } -ContentType 'application/json' -Body $body
$global:token = $r.access_token
$body = $null; $pwd = $null; $r = $null
"Token obtenido: " + ($global:token.Length -gt 0)
```

No imprimas `$global:token` ni lo pegues en ningún lado. Dura aproximadamente
una hora; si vence, repite este paso.

## Paso 6: probar las rutas

Define un ayudante (devuelve siempre el código de estado, aunque haya error):

```powershell
function Call([string]$Method, [string]$Path, $Body = $null, [string]$Token = $global:token) {
  $p = @{ Method = $Method; Uri = "$global:api$Path"; UseBasicParsing = $true }
  if ($Token) { $p.Headers = @{ Authorization = "Bearer $Token" } }
  if ($null -ne $Body) { $p.ContentType = 'application/json'; $p.Body = ($Body | ConvertTo-Json -Depth 5) }
  try {
    $r = Invoke-WebRequest @p
    [pscustomobject]@{ Status = [int]$r.StatusCode; Data = ($r.Content | ConvertFrom-Json); Raw = $r.Content }
  } catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
    [pscustomobject]@{ Status = $code; Data = $null; Raw = "$($_.ErrorDetails.Message)" }
  }
}
```

### 6.1 Acceso

```powershell
(Call GET  /health -Token '').Status                                           # 200
(Call POST /sessions @{ mode='random'; question_count=3 } -Token '').Status    # 401 (sin token)
(Call POST /sessions @{ mode='random'; question_count=3 } -Token 'basura').Status   # 401 (token falso)
```

### 6.2 Una sesión completa

```powershell
$c = Call POST /sessions @{ mode='random'; question_count=3 }
$c.Status                    # 201
$sid = $c.Data.id

$n1 = Call POST "/sessions/$sid/next"
$n1.Status                   # 200
$n1.Raw -match 'correct_option'          # False: la clave NO viaja con la pregunta
$n1.Data.deadline_at                      # ahora + 90 s
$n1.Data.options | Format-Table

$n2 = Call POST "/sessions/$sid/next"     # "recargar"
$n2.Data.deadline_at -eq $n1.Data.deadline_at     # True: el plazo no se reinicia

(Call GET "/sessions/$sid").Data          # current_position = 1, answered_count = 0
```

Errores esperados antes de responder:

```powershell
(Call POST "/sessions/$sid/answer" @{ position=2; selected_option='A' }).Status                  # 409 (no emitida)
(Call POST "/sessions/$sid/answer" @{ position=1; selected_option='E' }).Status                  # 422 (opción inexistente)
(Call POST "/sessions/$sid/answer" @{ position=1; selected_option='A'; user_id='x' }).Status     # 422 (campo extra)
```

Responder (a propósito mal) y reenviar:

```powershell
$a = Call POST "/sessions/$sid/answer" @{ position=1; selected_option='B' }
$a.Status; $a.Data           # 200; is_correct False; correct_option 'A'; time_used_ms
$a2 = Call POST "/sessions/$sid/answer" @{ position=1; selected_option='A' }
$a2.Data.selected_option     # 'B': devuelve el intento ya guardado, no lo reemplaza
```

Terminar la sesión:

```powershell
foreach ($i in 2,3) {
  $q = Call POST "/sessions/$sid/next"
  $null = Call POST "/sessions/$sid/answer" @{ position=$q.Data.position; selected_option='A' }
}
(Call GET "/sessions/$sid").Data.status            # completed
(Call POST "/sessions/$sid/next").Status           # 409
```

### 6.3 Abandonar y sesión inexistente

```powershell
$s2 = (Call POST /sessions @{ mode='area'; area='econometria'; question_count=2 }).Data.id
(Call POST "/sessions/$s2/abandon").Data.status    # abandoned
(Call POST "/sessions/$s2/next").Status            # 409
(Call GET "/sessions/00000000-0000-0000-0000-000000000000").Status   # 404
```

### 6.4 Timeout real (esperas 95 s)

```powershell
$s3 = (Call POST /sessions @{ mode='random'; question_count=2 }).Data.id
$q1 = Call POST "/sessions/$s3/next"
Start-Sleep -Seconds 95

$q2 = Call POST "/sessions/$s3/next"
$q2.Data.position                                   # 2: next registró el timeout de la 1 y emitió la 2
$q2.Data.deadline_at -gt $q1.Data.deadline_at       # True: plazo nuevo

$t = Call POST "/sessions/$s3/answer" @{ position=1; selected_option='A' }
$t.Data                                             # timed_out True, is_correct False, selected_option vacío, 90000 ms
```

### 6.5 Simulacro y ranking

```powershell
(Call POST /sessions @{ mode='simulacro'; stage='final' }).Data.question_count    # 4

# 20 preguntas distintas completadas -> aparece en el ranking
$s20 = (Call POST /sessions @{ mode='random'; question_count=20 }).Data.id
1..20 | ForEach-Object {
  $q = Call POST "/sessions/$s20/next"
  $null = Call POST "/sessions/$s20/answer" @{ position=$q.Data.position; selected_option='A' }
}
(Call GET "/sessions/$s20").Data.status             # completed
```

### 6.6 (Opcional) Una segunda persona: sesión ajena = 404

Crea otro usuario en Authentication, añade su perfil en el mismo equipo con
SQL (el equipo admite cinco personas) y obtén su token como en el paso 5:

```sql
insert into public.profiles(id, team_id, display_name)
select u.id, (select id from public.teams where name = 'Equipo de prueba'), 'Segunda persona'
from auth.users u where u.email = 'CORREO_DE_LA_SEGUNDA_PERSONA';
```

```powershell
(Call GET "/sessions/$sid" -Token $token2).Status   # 404: la sesión es de la primera persona
```

## Paso 7: verificar en la base (SQL Editor, solo lectura)

```sql
select s.id, s.mode, s.status, a.position, a.selected_option,
       a.is_correct, a.timed_out, a.time_used_ms
from public.sessions s join public.attempts a on a.session_id = s.id
order by s.started_at, a.position;

select display_name, rank_position, questions_seen, correct_count,
       accuracy_pct, avg_time_seconds, sessions_completed
from public.practice_ranking;
```

Debes ver: un intento con `timed_out = true` y 90000 ms (6.4), y en el ranking
tu usuario con `questions_seen >= 20` y `rank_position = 1`.

## Paso 8: qué reportarme

Solo esta tabla, sin tokens ni claves:

| Prueba | Esperado | Obtenido |
| --- | --- | --- |
| 6.1 sin token / token falso | 401 / 401 | |
| 6.2 crear sesión | 201 | |
| 6.2 pregunta sin `correct_option` | `False` | |
| 6.2 recargar conserva `deadline_at` | `True` | |
| 6.2 posición no emitida / opción `E` / campo extra | 409 / 422 / 422 | |
| 6.2 reenviar devuelve el primero | `B` | |
| 6.2 sesión completada y `next` | `completed` / 409 | |
| 6.3 abandonar y `next` / inexistente | `abandoned`, 409 / 404 | |
| 6.4 timeout con `next` | posición 2, `timed_out True` | |
| 6.5 simulacro final | 4 preguntas | |
| 6.5 ranking | puesto 1, 20 vistas | |

## Problemas frecuentes

| Síntoma | Causa probable |
| --- | --- |
| 401 con token recién obtenido | La URL o la clave son de otro proyecto, o el token venció. |
| 403 | El usuario existe en Auth pero no tiene perfil (paso 2). |
| 503 `Base de datos no disponible` | `DATABASE_URL` mal copiada, contraseña sin codificar, o la conexión directa requiere IPv6: usa *Session pooler*. |
| 503 `Autenticación no configurada` | Faltan `SUPABASE_URL` o `SUPABASE_PUBLISHABLE_KEY` en la Terminal 1. |
| 503 `No se pudo verificar la sesión` | Supabase Auth no respondió; reintenta. |
| 409 al crear sesión | No hay suficientes preguntas activas (¿ejecutaste el paso 2?). |
| El paso 5 falla con "Email not confirmed" | El usuario se creó sin *Auto Confirm User*. |

## Limpieza

1. Detén uvicorn (`Ctrl+C` en la Terminal 1) y cierra ambas terminales: las
   variables desaparecen con la sesión.
2. Ejecuta el bloque de limpieza (comentado) al final de
   [`prueba-backend-datos.sql`](prueba-backend-datos.sql), solo en
   `pruebas_cane`.
3. Borra el usuario desde **Authentication > Users**.
