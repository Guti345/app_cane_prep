# CANE Prep

App de práctica para cinco integrantes de un equipo, con preguntas de
Microeconomía, Macroeconomía, Econometría e Historia y Pensamiento Económico.

## Estado real

**Solo existe un arranque local mínimo.** No hay inicio de sesión, preguntas,
ranking, base de datos aplicada ni despliegues.

| Pieza | Estado |
| --- | --- |
| Frontend (Vite + TypeScript) | Login, inicio, pregunta con cronómetro de 90 s, resultado, resumen y ranking, con Markdown, LaTeX (KaTeX) y figuras. **Probado en local** (pruebas unitarias y un recorrido contra el backend local) **y en un navegador real contra `pruebas_cane`** (login, sesión con cronómetro, recarga, ranking, CORS); sin probar en móvil ni con lector de pantalla, y sin desplegar |
| Backend (FastAPI) | `GET /health`, CORS y la API de juego (sesiones, preguntas, respuestas, intentos y ranking) con autenticación por Supabase Auth y repositorio PostgreSQL. **Probada en local** (PostgreSQL local y un Auth falso) **y contra el proyecto de pruebas** `pruebas_cane` con Auth y PostgreSQL reales; aislamiento entre compañeros y entre equipos verificado en Supabase real; sin desplegar y sin comprobar aún la Data API. Sin configuración, las rutas de juego responden 503 |
| Supabase | `config.toml` y dos migraciones, **ninguna aplicada al proyecto real**: el esquema (probada en un proyecto de pruebas, 14/14) y la curación del banco (solo probada en PostgreSQL local). Guía en [`docs/supabase.md`](docs/supabase.md) |
| Banco de preguntas | Importador (`scripts/importar_banco.py`) probado en local con las 483 preguntas (427 activas); **sin cargar** en pruebas ni en el real. Markdown/LaTeX y figuras implementados y probados en local con el banco real (a 390 px); las figuras viven en PostgreSQL y las sirve la API. Guía en [`docs/importador.md`](docs/importador.md) |
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
    src/               main.ts, app.ts, api.ts, play.ts, timer.ts,
                       supabase.ts, router.ts, screens/, *.test.ts
    netlify.toml       build y publicación (base del sitio: frontend)
    .env.example       VITE_API_URL, VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY
  backend/             FastAPI
    app/               main.py, config.py, domain.py, schemas.py,
                       routes_game.py, dependencies.py,
                       supabase_auth.py, postgres.py
    tests/             pruebas de API y autenticación; integration/ prueba
                       el repositorio contra la migración (PostgreSQL local)
    requirements.txt, requirements-dev.txt, .env.example
  supabase/
    config.toml        Configuración de la CLI (preexistente)
    migrations/        Dos migraciones: ninguna aplicada al real
  scripts/             importar_banco.py y su curación (lee private-data/)
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
