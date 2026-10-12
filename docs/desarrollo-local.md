# Desarrollo local

Comandos para PowerShell en Windows. En macOS/Linux, el entorno virtual se
activa con `source .venv/bin/activate`.

## Requisitos

| Herramienta | Versión |
| --- | --- |
| Node.js | `^20.19.0` o `>=22.12.0` (requisito de Vite 8); probado con 24.14.1 |
| npm | probado con 11.11.0 |
| Python | probado con 3.14.5; ver nota abajo |

Nota sobre Python: los requisitos no fijan una versión concreta. Al desplegar
en Render habrá que fijarla y comprobar que se admite
(ver [`decisiones-pendientes.md`](decisiones-pendientes.md)).

## Backend (terminal 1)

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

- Comprobación manual: <http://localhost:8000/health> → `{"ok":true}`.
- No necesita Supabase ni contraseñas.
- Variable opcional: `FRONTEND_ORIGIN` (orígenes separados por comas; no
  admite `*`). Por defecto, `http://localhost:5173`. La app lee el entorno del
  proceso, no carga `.env` automáticamente:

  ```powershell
  $env:FRONTEND_ORIGIN = "http://localhost:5173"
  ```

## Frontend (terminal 2)

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Abre <http://localhost:5173>. La aplicación necesita las **tres** variables
públicas de `frontend/.env`; si falta alguna, muestra un aviso con sus
nombres en lugar de una pantalla en blanco:

| Variable | Valor |
| --- | --- |
| `VITE_API_URL` | URL del backend, p. ej. `http://localhost:8000` |
| `VITE_SUPABASE_URL` | URL del proyecto de **pruebas** (Project Settings > API) |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Clave *publishable* del proyecto de pruebas |

`frontend/.env` está ignorado por Git. Nunca pongas ahí secretos, porque todo
lo que empieza con `VITE_` termina en el navegador (la clave publicable es
pública por diseño; una `secret`/`service_role` jamás va aquí). Para jugar
hacen falta el backend configurado y un usuario con perfil: ver
[`prueba-backend-pruebas.md`](prueba-backend-pruebas.md). La pantalla de login
incluye un botón para comprobar la conexión con el backend.

## Comprobaciones

```powershell
# Frontend
cd frontend
npm run typecheck
npm test
npm run build

# Backend (con el entorno virtual activado)
cd backend
python -m pytest
```

### Pruebas de integración (PostgreSQL local)

`backend/tests/integration/` prueba el repositorio contra **la migración real**
en un PostgreSQL local (PGlite, en memoria, vía Node). No toca Supabase ni
ningún proyecto remoto. Instalación, una sola vez:

```powershell
cd backend\tests\integration\pglite
npm install
```

Si no está instalado, esas pruebas se **omiten** (no fallan). PGlite es
PostgreSQL real pero no es Supabase; ver los límites en
[`arquitectura.md`](arquitectura.md).

### Recorrido del frontend contra un backend real

`frontend/src/e2e.test.ts` recorre una sesión completa con la lógica del
cliente. Se omite si no hay variables. Para correrlo contra el backend de la
guía [`prueba-backend-pruebas.md`](prueba-backend-pruebas.md) (proyecto de
**pruebas**), con el token ya obtenido en esa terminal:

```powershell
cd frontend
$env:CANE_E2E_API_URL = "http://localhost:8000"
$env:CANE_E2E_TOKEN = $global:token      # no lo escribas en archivos
npm test -- src/e2e.test.ts
```

Compilar el frontend no demuestra que CORS ni el despliegue funcionen; eso se
comprueba con ambos servicios en marcha y, más adelante, con las URL reales.

## Netlify (aún sin configurar)

El sitio debe configurarse con **base directory = `frontend`**. Con esa base,
`frontend/netlify.toml` usa `npm run build` y publica `dist` (relativo a la
base; no `frontend/dist`). Hay que definir `VITE_API_URL` en Netlify con la URL
real del backend y poner el origen de Netlify en `FRONTEND_ORIGIN` del
backend.

## `private-data/` (solo local)

`private-data/` está ignorada por Git: **Git no la conserva** y no existe tras
clonar el repositorio. Cada integrante la crea cuando la necesite:

```powershell
New-Item -ItemType Directory -Force private-data\lotes, private-data\originales
```

- `private-data/originales/`: PDF de la guía y recursos originales.
- `private-data/lotes/`: JSON convertidos por lote.

No copies su contenido a `frontend/public/`, `docs/`, `supabase/` ni a otra
ruta versionada: contiene respuestas correctas.
