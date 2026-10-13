# Pruebas con Supabase Auth real (proyecto de pruebas)

> **Resultado (2026-10-13, usuario *Segunda persona*, backend local sobre
> `pruebas_cane`):** las 2 pruebas e2e pasan; el recorrido completo con un JWT
> real funciona; la Data API con ese JWT responde `403 / 42501` en las 9
> tablas y vistas y en las 5 escrituras probadas. Detalle al final.

Hasta ahora el recorrido completo se probó con tokens fijos de un arnés local.
Esta guía lo prueba con un **inicio de sesión real** de un usuario de pruebas.
Todo ocurre contra `pruebas_cane` (`yqhtmrlwxgvxyiekzscb`); los scripts se
niegan a operar con el proyecto real.

## 1. Obtener un token real (lo haces tú, en tu terminal)

```powershell
# Desde la raíz del repositorio
backend\.venv\Scripts\python scripts\prueba_auth.py
```

- Pide el **correo** y la **contraseña** (esta con `getpass`: no se ve, no queda
  en el historial ni se pasa como argumento).
- Inicia sesión con Supabase Auth (`/auth/v1/token?grant_type=password`, lo mismo
  que hace `signInWithPassword` del navegador).
- Guarda el token en `private-data/token_prueba.json` (ignorado por Git) y **no
  lo imprime**. Dura lo que dure el token (normalmente 1 hora).
- La clave publicable (pública por diseño) la toma de `SUPABASE_PUBLISHABLE_KEY`
  o de la CLI de Supabase (`projects api-keys`, que enmascara las secretas).
- Para borrarlo: `backend\.venv\Scripts\python scripts\prueba_auth.py --borrar`.

**Qué usuario.** Cualquiera de los tres perfiles de prueba sirve. Para poder
comprobar que una sesión **ajena** no entrega su figura, conviene *Segunda
persona* (no es dueña de la sesión de prueba anterior, que es de *Persona de
prueba*).

## 2. Backend local con Auth real y pruebas_cane

```powershell
backend\.venv\Scripts\python scripts\backend_pruebas.py                       # :8000
backend\.venv\Scripts\python scripts\backend_pruebas.py --port 8001 --solo-figuras
```

- Usa `SupabaseTokenVerifier` (valida cada token con Supabase Auth) y la base de
  pruebas. La cadena sale de `private-data/importador.env` y no se imprime.
- Solo escucha en `127.0.0.1`/`localhost` o en una dirección de red privada
  (192.168.x.x, 10.x.x.x, 172.16-31.x.x). Rechaza `0.0.0.0` y las públicas.
- `--solo-figuras` es solo para pruebas: las sesiones eligen entre las preguntas
  activas que tienen figura (cambia la consulta, no los datos).
- `--origin URL` (repetible) fija los orígenes que CORS permite.

## 3. Pruebas e2e omitidas

`frontend/src/e2e.test.ts` tiene 2 pruebas que se omiten salvo que existan
`CANE_E2E_API_URL` y `CANE_E2E_TOKEN`:

1. **Sesión completa** (`random`, 3 preguntas): cada pregunta, responder,
   resultado, resumen y ranking. Comprueba que no llega `correct_option` antes de
   responder y que el plazo, corregido con la hora del servidor, queda en (0, 90] s.
2. **Recargar a mitad de sesión**: la misma pregunta con el mismo plazo; luego
   abandona la sesión.

```powershell
$env:CANE_E2E_API_URL = "http://127.0.0.1:8000"
$env:CANE_E2E_TOKEN = (Get-Content private-data\token_prueba.json | ConvertFrom-Json).access_token   # no lo imprimas
cd frontend
npx vitest run src/e2e.test.ts
Remove-Item Env:CANE_E2E_TOKEN
```

Las pruebas declaran un tiempo de 90 s por prueba: contra servicios remotos cada
petición pasa por Supabase Auth y la base, y los 5 s por defecto de vitest no
alcanzan (la primera corrida falló por eso, no por comportamiento).

Efecto en la base: la primera crea una sesión **completada** con 3 intentos del
usuario; la segunda, una sesión **abandonada**. No se borra nada.

## 4. Data API con el JWT del usuario

El 401 de la clave anónima, por sí solo, **no demuestra nada**: solo dice que un
visitante sin sesión no entra. Lo que cuenta es el caso **autenticado** (un JWT
de usuario real) más los privilegios por SQL (`has_table_privilege` falso para
`anon` y `authenticated`, RLS activado, sin políticas).

Se prueba cada tabla y vista que crean las migraciones del repo: `teams`,
`profiles`, `questions`, `question_keys`, `question_assets`, `sessions`,
`session_questions`, `attempts` y `practice_ranking`. Además, escrituras
inofensivas (`POST {}`) en las que importan.

La figura **no** es accesible por la Data API con rol de usuario. Sí lo es para
quien tenga la clave `service_role` o el rol `postgres` (el backend usa
`postgres`); eso es el diseño, no una imposibilidad: la protección es no exponer
esa clave al navegador y servir la figura solo por el endpoint del backend, que
exige sesión propia y pregunta ya emitida.

## 5. Probar desde el celular (misma Wi-Fi, sin desplegar)

Requisitos: el celular y el PC en la **misma red Wi-Fi** (no una red de
invitados con aislamiento de clientes). El PC con la red marcada como
**Privada** en Windows.

1. **IP del PC** en esa Wi-Fi: `ipconfig` → "Adaptador de LAN inalámbrica
   Wi-Fi" → "Dirección IPv4" (en esta máquina: `192.168.1.3`; puede cambiar).
   Usa esa IP donde diga `IP` abajo.
2. **Backend** (terminal 1, en la raíz):

   ```powershell
   backend\.venv\Scripts\python scripts\backend_pruebas.py --host IP --port 8000 --origin http://IP:5173
   ```

   `--origin` es el cambio de CORS, solo para esta prueba; no toca el código ni
   `.env`.
3. **Frontend** (terminal 2):

   ```powershell
   cd frontend
   $env:VITE_API_URL = "http://IP:8000"      # solo en esta terminal; pisa frontend/.env
   npm run dev -- --host IP --port 5173
   ```

   Las variables `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY` de
   `frontend/.env` deben ser las del proyecto de **pruebas**.
4. **Firewall**: Windows preguntará si permite `node` y `python` en redes
   privadas: acepta **solo "Redes privadas"**. Al terminar, detén los dos
   procesos (Ctrl+C) y, si quieres, elimina esas reglas en "Firewall de Windows
   Defender con seguridad avanzada".
5. **Celular**: abre `http://IP:5173`, inicia sesión con un usuario de pruebas y
   haz una sesión corta. Conviene incluir una pregunta con figura
   (econometría 6, 8, 56, 59 o 61; microeconomía 1, 24 o 28) y una con
   ecuación.

Qué mirar: legibilidad de ecuaciones y tablas, que la figura cargue, el cronómetro
(mostrar 1:30 al abrir y que no se reinicie al recargar), el teclado al iniciar
sesión, y ecuaciones anchas (se desplazan en horizontal sin señal visual).

Notas:

- Es `http`, no `https`: es suficiente para el inicio de sesión por contraseña.
  Si el navegador del celular se quejara de funciones que exigen contexto
  seguro, avísalo; no se resuelve con túneles públicos.
- Si la red aísla los dispositivos (la página no abre desde el celular aunque
  la IP sea correcta), alternativas **sin ejecutar nada hasta decidirlo**: usar
  el punto de acceso del celular y conectar el PC a él; cable USB con
  anclaje de red; o un despliegue de prueba en Netlify/Render (requiere
  decisión y sí expone un servicio).

## 6. Render

El backend lee **`DATABASE_URL`** (más `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`
y `FRONTEND_ORIGIN`). En Render debe ser la cadena **Session pooler** de
Supabase (host `aws-0-<región>.pooler.supabase.com`, puerto 5432, usuario
`postgres.<ref>`): la conexión directa (`db.<ref>.supabase.co`) exige IPv6 y no
hay evidencia (sin verificar) de que Render lo ofrezca. La del pooler es la misma familia que usa el importador
desde este PC, pero esa prueba **no demuestra** que Render alcance ese host:
solo se comprueba al desplegar. El código ya funciona con el pooler: usa
`sslmode=require` y no emplea sentencias preparadas.

## Resultado de la corrida del 2026-10-13

| Qué | Resultado |
| --- | --- |
| e2e 1 (sesión completa, 3 preguntas) | Pasa (13 s) |
| e2e 2 (recargar a mitad) | Pasa (5,5 s) |
| `/auth/v1/user` con el JWT | 200, rol `authenticated`, correo confirmado |
| `POST /sessions` (área, 1 pregunta, con figura) | 201 |
| `POST /next` | 200; sin clave en la respuesta |
| Figura | 200, `image/png`, 16 798 bytes, idéntica (sha256) al archivo importado; otra posición 404; sin token 401 |
| Sesión anterior de *Persona de prueba* (ajena) | sesión 404 y figura 404 |
| `POST /answer` | 200; la opción correcta llega solo después de responder |
| Siguiente | 409 (no quedan); sesión `completed` |
| `/attempts` y `/ranking` | 200; ranking del equipo con 2 filas; sin puesto (< 20 preguntas) |
| Data API, 9 tablas/vistas (lectura) | 403, `42501 permission denied` en todas |
| Data API, `POST {}` en attempts, question_keys, question_assets, questions, sessions | 403, `42501` |

**Efecto en `pruebas_cane`:** 5 sesiones nuevas de *Segunda persona* (3
completadas con 7 intentos entre todas, 2 abandonadas; una quedó `active` por la
primera corrida cortada por tiempo y se cerró con `abandon`), 12 filas en
`session_questions`, 7 en `attempts`. El login actualizó
`auth.users.last_sign_in_at`/`updated_at` y creó una sesión de Auth (lo normal de
Supabase). `public.profiles` no cambió (hash idéntico). Las 483 preguntas, claves,
figuras, perfiles y equipos no cambiaron.

**Qué no cubre.** El 401 anónimo, por sí solo, no demuestra nada; el caso
autenticado y los privilegios por SQL sí. No se probó la pantalla de login del
navegador (no se teclea una contraseña en un navegador automatizado); el inicio
de sesión usa el mismo endpoint de Auth que `signInWithPassword`.
