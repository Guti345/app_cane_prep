# CANE Prep

App de práctica para cinco integrantes de un equipo, con preguntas de
Microeconomía, Macroeconomía, Econometría e Historia y Pensamiento Económico.

## Estado real

**Solo existe un arranque local mínimo.** No hay inicio de sesión, preguntas,
ranking, base de datos aplicada ni despliegues.

| Pieza | Estado |
| --- | --- |
| Frontend (Vite + TypeScript) | Pantalla con un botón que consulta `GET /health` |
| Backend (FastAPI) | Solo `GET /health` → `{"ok": true}` y CORS |
| Supabase | Solo `config.toml` de la CLI; sin migraciones. La guía está en [`docs/supabase.md`](docs/supabase.md); nada aplicado al remoto |
| Netlify / Render | Sin configurar ni desplegar |

## Alcance

El MVP previsto incluye acceso individual, práctica por área y simulacro,
cronómetro de 90 segundos controlado por el servidor, feedback inmediato y
ranking individual (mínimo 20 preguntas). Nada de esto está implementado.
Decisiones abiertas: [`docs/decisiones-pendientes.md`](docs/decisiones-pendientes.md).

## Arquitectura

Frontend estático (Netlify) → API FastAPI (Render) → PostgreSQL (Supabase).
El navegador usa Supabase **solo para Auth**; el contenido y las operaciones
del juego pasan por FastAPI y las respuestas correctas no se envían antes de
responder. Para operaciones atómicas, el backend usará una conexión PostgreSQL
directa (por implementar). Detalle en [`docs/arquitectura.md`](docs/arquitectura.md).

## Estructura

```
app_cane_prep/
  README.md
  .gitignore
  frontend/            Vite + TypeScript sin framework
    src/               main.ts, api.ts, styles.css
    netlify.toml       build y publicación (base del sitio: frontend)
    .env.example       VITE_API_URL
  backend/             FastAPI
    app/               main.py, config.py
    tests/             test_health.py
    requirements.txt, requirements-dev.txt, .env.example
  supabase/
    config.toml        Configuración de la CLI (preexistente)
    migrations/        Vacía; aún sin migraciones
  docs/                arquitectura, desarrollo local, decisiones pendientes
  private-data/        SOLO LOCAL e ignorada por Git (no existe al clonar)
```

`private-data/` no la conserva Git: cada integrante debe crearla cuando la
necesite (ver [`docs/desarrollo-local.md`](docs/desarrollo-local.md)).

## Requisitos

- Node.js `^20.19.0` o `>=22.12.0` y npm.
- Python 3 (probado con 3.14.5).

## Comandos locales

Dos terminales, desde la raíz del repositorio (PowerShell):

```powershell
# Terminal 1: backend
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2: frontend
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Frontend en <http://localhost:5173>, backend en <http://localhost:8000>.

## Comprobaciones

```powershell
cd frontend; npm run typecheck; npm run build
cd backend;  python -m pytest      # con el entorno virtual activado
```

## Seguridad

- Nunca versiones `.env`, claves ni cadenas de conexión. Solo `.env.example`.
- `private-data/`, PDF resaltados y JSON con `correct_option` no se versionan.
- El frontend no recibe credenciales privadas; todo `VITE_*` es público.
