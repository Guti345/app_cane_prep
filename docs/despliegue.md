# Despliegue: Render, Netlify y arranque en frío

Guía para publicar CANE Prep con planes gratuitos. **Nada de esto está desplegado
todavía.** No contiene hosts, cadenas de conexión ni claves: se toman del panel de cada
servicio en el momento. Fecha de esta versión: 2026-10-14.

## 1. Piezas y variables

| Variable | Dónde | Visibilidad | Qué hace |
| --- | --- | --- | --- |
| `DATABASE_URL` | Render | **secreta** | Cadena del *Session pooler* del proyecto de Supabase (botón **Connect**). Solo en el panel de Render o en un archivo local ignorado; nunca en `VITE_*`, Git, docs ni chat |
| `SUPABASE_URL` | Render | configuración | URL del proyecto; valida el token del usuario |
| `SUPABASE_PUBLISHABLE_KEY` | Render | configuración | Clave *publishable* (pública por diseño). Nunca `secret`/`service_role` |
| `FRONTEND_ORIGIN` | Render | configuración | Origen exacto de Netlify (esquema + host, sin ruta ni `*`). Admite varios separados por comas |
| `ENABLE_API_DOCS` | Render | configuración | **No la definas en producción.** Solo `1`/`true` publica `/docs`, `/redoc` y `/openapi.json` |
| `PYTHON_VERSION` | Render | configuración | Ver sección 2 |
| `VITE_API_URL` | Netlify | pública | URL de Render (la que muestra su panel) |
| `VITE_SUPABASE_URL` | Netlify | pública | La misma URL de proyecto que `SUPABASE_URL` |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Netlify | pública | La misma clave *publishable* |

- Las tres `VITE_*` son **obligatorias** (la app las lee al arrancar) y Vite las **incrusta
  en el build**: cualquier cambio exige un deploy nuevo en Netlify.
- Auth y backend deben apuntar al **mismo** proyecto de Supabase: la URL y la clave de
  `VITE_SUPABASE_*` y las de `SUPABASE_*` salen del mismo panel.
- El token de un proyecto no sirve en el otro: si no coinciden, todo responde 401.

## 2. Render (backend)

| Campo | Valor |
| --- | --- |
| Tipo | Web Service, repositorio del proyecto |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Plan | Free (confirmar en el panel; no introducir tarjeta) |
| Health check path (Advanced) | `/health` — opcional; **solo prueba el proceso, no la base** |

**Python.** Render solo admite `PYTHON_VERSION` completa (`x.y.z`). Su documentación
dice que admite cualquier versión publicada desde 3.7.3 y que el valor por defecto de
los servicios creados desde 2026-02-11 es **3.14.3**; no nombra 3.14.5. El backend se
probó con 3.14.5. Compatibilidad de las dependencias fijadas (consultada en PyPI el
2026-10-14): `psycopg-binary 3.3.6` y `pydantic-core 2.50.0` publican ruedas `cp314`
para `manylinux` x86_64; `fastapi`, `uvicorn`, `httpx` y `psycopg-pool` son Python puro.
Eso indica que **no habrá compilación**, pero **solo el build real lo confirma**: la
línea de versión de Python y la instalación de `psycopg-binary` en el log del primer
deploy son la prueba. Si Render rechaza `3.14.5`, usar `3.14.3` (su valor por defecto,
documentado) y volver a ejecutar las pruebas contra esa versión antes de darlo por bueno.

## 3. Netlify (frontend)

- Repositorio y commit publicados; **Base directory** `frontend`.
- Build y publicación salen de `frontend/netlify.toml`: `npm run build`, `dist`
  (relativo a la base). `NODE_VERSION = "22"` cumple `engines >= 22.12.0`.
- No hace falta regla de redirección: el router usa el *hash* (`#/ranking`, `#/jugar/...`).
- No subir el `dist` local: contiene la URL del proyecto con el que se construyó. Netlify
  debe construir con sus propias variables.

## 4. Orden de URLs sin `*` en CORS

1. **Render** con `FRONTEND_ORIGIN` = el origen local que se necesite para verificar
   (`http://localhost:5173`); desplegar y copiar la URL que muestra el panel.
2. **Netlify** con `VITE_API_URL` = esa URL; construir y copiar la URL pública.
3. **Render**: `FRONTEND_ORIGIN` = la URL de Netlify (sin barra final ni ruta) y comprobar
   que el servicio se reinició con el valor nuevo.
4. Quitar el origen local de `FRONTEND_ORIGIN` si ya no hace falta.

Una URL de *deploy preview* de Netlify es otro origen y quedará rechazada: es lo deseado.
Un dominio propio habría que añadirlo, separado por coma.

## 5. Arranque en frío (plan gratuito de Render)

Hechos del plan (fuente: documentación de Render, consultada el 2026-10-14): el servicio
gratuito se duerme tras **15 minutos sin tráfico entrante**; la siguiente petición lo
despierta y "tarda alrededor de un minuto"; mientras tanto Render muestra una página de
carga a los navegadores. Render puede reiniciar un servicio gratuito en cualquier momento.
El tiempo real de despertar **no está medido** (ver sección 8).

Qué hace el cliente (`frontend/src/api.ts`, `play.ts`, `screens/home.ts`):

| Operación | Calentamiento previo | Espera máxima | Reintento |
| --- | --- | --- | --- |
| Abrir la app o el inicio | `GET /health`, sin esperar por él, solo si pasaron >10 min sin respuesta | hasta ~75 s | acotado (3 intentos) |
| **Crear sesión** (`POST /sessions`) | **Sí**, antes de enviar | 15 s tras despertar | **Ninguno**. Si no despierta, no se envía (`not_sent`) y es seguro repetir. Si se envía y la respuesta se pierde, el resultado es **incierto** y queda un bloqueo persistente (sección 6) |
| **Responder** (`POST .../answer`) | **Nunca** | 15 s | **Ninguno automático** |
| Recuperar/continuar (`POST .../next`) | **Nunca** (se envía de inmediato) | 75 s si el servidor pudo dormirse; 15 s si no | **Ninguno automático**. No es una lectura: ver abajo |
| Lecturas (`GET` sesión, intentos, ranking, figuras) | No | 75 s si pudo dormirse; 15 s si no | Uno, solo ante fallo de red o 503 |

- **El reloj de 90 s es el del servidor** (`deadline_at`, `server_now`). El cliente solo
  resta: nada de esto pausa, reinicia ni amplía el plazo. La respuesta de una pregunta
  activa se envía enseguida, con la espera normal, sin calentamiento.
- **Aviso accesible:** una región `role="status"` / `aria-live="polite"` escribe una sola
  vez "Despertando el servidor…" si una espera con el servidor posiblemente dormido pasa de
  4 s, y la borra al terminar. No hay contador hablado por segundo.
- **`POST .../next` no es una lectura.** Repite la pregunta pendiente con el mismo
  `deadline_at`, pero si esa pregunta ya venció **registra su timeout y emite la siguiente**
  (o cierra la sesión con 409). Por eso el cliente nunca lo repite solo ni lo trata como
  un GET; lo repite la persona con "Reintentar". Consecuencia, inherente a la API: si la
  respuesta de un `/next` que sí emitió la pregunta se pierde y la persona tarda más de
  90 s en reintentar, esa pregunta queda como sin respuesta (el reloj es el del servidor).
  Reintentar antes del plazo devuelve la misma pregunta con el tiempo que le quede.
- **Respuesta perdida** (`POST .../answer` sin resultado): no se reenvía sola. Se
  resincroniza con `GET /sessions/{id}/attempts`: si el intento está guardado, se muestra
  ese resultado; si el servidor confirma que **no** está, se ofrece reenviar la misma
  posición y opción; si no se pudo comprobar, se ofrece comprobar de nuevo. Un GET fallido
  **no** significa "no se guardó".
- **Sin mantenimiento:** no hay pings periódicos, cron, bots ni nada que evite el reposo.
  El único `GET /health` lo dispara una persona al abrir la app o antes de crear una sesión.

## 6. `POST /sessions` con la respuesta perdida (resultado incierto)

`POST /sessions` **no es idempotente** y la API no tiene un endpoint de sesión activa (las
rutas son: crear sesión; leer, `next`, `answer`, `attempts`, `abandon` y figuras de una
sesión **por su id**; y `ranking`). Si el servidor creó la sesión pero la respuesta se
perdió, el cliente no conoce el id y no puede saber si existe ni recuperarla.

Qué hace el cliente (`frontend/src/pendingCreate.ts`, `screens/home.ts`):

- **Marca antes de enviar.** Justo antes del POST (y solo si llega a enviarse) guarda en el
  navegador una marca ligada al usuario (`cane.pendingCreate.v1.<id del usuario>`) que solo
  contiene el momento. **No guarda token ni datos de la sesión.**
- **Resultado definitivo = se borra:** sesión creada, o un 4xx del servidor (rechazó: nada se
  creó), o `not_sent` (no se llegó a enviar).
- **Resultado incierto (corte, tiempo agotado, 5xx, recarga con la petición en vuelo) = se
  conserva.** "Empezar" queda bloqueado, también tras **recargar**, volver a abrir la
  pestaña o cerrar sesión y volver a entrar **con la misma cuenta**. Otra cuenta en el mismo
  navegador no hereda el bloqueo.
- **Qué NO lo libera:** recargar, cerrar sesión, ni encontrar una sesión activa con un GET
  (la que se encuentre no tiene por qué ser la de la petición perdida), ni un GET vacío o
  fallido (la petición original aún pudo completarse).
- **Cómo se continúa:** durante 10 minutos (tiempo en que la petición original aún pudo
  completarse) no hay forma de continuar. Pasados, aparece un botón que exige **reconocer**
  que pudo quedar una sesión sin usar. Ese reconocimiento es una decisión informada de la
  persona, **no** una recuperación de la operación: la sesión perdida sigue sin mostrarse.
  Una sesión sin respuestas no entra en el ranking (solo cuentan intentos en sesiones
  completadas).
- **Sin almacenamiento** (modo privado, bloqueado): el bloqueo vale mientras la página siga
  abierta; no hay garantía tras recargar. Es una limitación del navegador, no un fallo.
- Borrar manualmente los datos del sitio elimina la marca; no se presenta como recuperación.

**Cambio mínimo para recuperarla de verdad (NO implementado; requiere tu revisión):**
`POST /sessions` aceptaría un `client_request_id` (UUID que genera el cliente antes de
enviar y que conserva con la marca) y lo guardaría con unicidad por usuario; repetir la
petición con el mismo identificador devolvería la sesión ya creada. Es determinista y
resuelve el caso exacto (no confunde la sesión con otra). **Límites:** exige una
**migración** (columna y restricción única en `sessions`) y un cambio del contrato de
`POST /sessions`; no ayuda con sesiones perdidas antes de existir el identificador.
Alternativa sin migración, **menos exacta**: `GET /sessions/active` (la sesión activa más
reciente del usuario): no distingue la sesión perdida de otra activa legítima.

## 7. Diagnóstico de un 503 de base de datos

`/health` prueba el proceso; **no** la conexión con la base. Un 503 aislado no identifica la
causa. El backend registra, sin el mensaje de la excepción, sin host, usuario, cadena ni
token, una línea como `Base de datos no disponible: <Clase> (sqlstate=<código>)`.

Rutas de log cubiertas (verificadas con pruebas y con un uvicorn real, ver
`backend/tests/test_operacion.py`):

| Ruta | Qué ocurre |
| --- | --- |
| Errores de conexión/pool (`OperationalError`, `PoolTimeout`) | 503 y una línea con clase y SQLSTATE |
| Cualquier otro error de psycopg (SQL, datos, integridad) | 500 `Error interno` y una línea con clase y SQLSTATE; sin traceback con el mensaje |
| Avisos del pool de psycopg (`psycopg.pool`, `psycopg_pool.sched*`) y de `psycopg` | La excepción de los argumentos se sustituye por clase y SQLSTATE |
| `logger.exception` / traceback que imprime uvicorn (`uvicorn.error`) | Se conservan las líneas de código de la pila y la clase; se elimina el mensaje |

Límite: la pila incluye líneas de **código fuente**, no valores de variables ni mensajes. El
registro de acceso de uvicorn muestra método, ruta (con el id de sesión) y estado; el token
viaja en una cabecera que no se registra.

| Línea en el log | Lectura probable | Qué mirar |
| --- | --- | --- |
| `InvalidPassword (sqlstate=28P01)` | Credenciales rechazadas | Contraseña/usuario de `DATABASE_URL` |
| `InvalidAuthorizationSpecification (...)` u otro `28xxx` | Autenticación/rol | Usuario del pooler y proyecto |
| `OperationalError` sin sqlstate | Conexión o TLS (libpq no dio código) | Ver abajo |
| `PoolTimeout` | El pool no consiguió conexión a tiempo (p. ej. aún conectando tras despertar, o base inalcanzable) | Reintentar; si persiste, tratar como conexión |
| `AdminShutdown` / `CannotConnectNow` (`57P01`/`57P03`) | La base se reinicia o está en pausa | Estado del proyecto en Supabase |

Para separar **conexión** de **TLS** con evidencia segura, el siguiente paso es una
comprobación local con la misma cadena que *no* imprima la cadena (resolución de nombre,
conexión TCP y apretón TLS por separado). No está hecha: se prepara solo si el log no basta.
Un pooler en modo transacción no es una alternativa "ya validada": hay que probarla contra
el proyecto real con evidencia antes de cambiar la cadena.

## 8. Medir el despertar real (sin pings)

1. Dejar el servicio sin usar **20 minutos o más**, sin visitas ni comprobaciones.
2. Abrir la app desde el navegador del computador y tomar el tiempo hasta que el aviso
   desaparece y la pantalla responde. En DevTools → Network, anotar el tiempo de espera de la
   primera petición.
3. En los logs de Render, anotar la hora de la primera línea de arranque y la de la primera
   petición atendida.
4. Anotar el resultado tal cual, sin extrapolar; repetir si hace falta con otro reposo.

Los 30-50 s de despertar y los 40-70 MB de RAM mencionados en una recomendación previa son
**hipótesis**, no mediciones. La memoria se mira en las métricas del panel de Render contra
el límite que muestre ese panel.

## 9. Sin verificar al escribir esto

- Que Render admita `PYTHON_VERSION=3.14.5` y que el build use las ruedas listadas.
- Que Render alcance el *Session pooler* de Supabase (el pooler compartido es solo IPv4 en
  todos los planes, según la documentación de Supabase; falta comprobarlo desde Render).
- El comportamiento exacto de Render ante un `fetch` durante el despertar (si retiene la
  petición o responde 502/503 sin cabeceras CORS; el navegador lo vería como error de red).
- CPU/RAM y ancho de banda incluido del plan gratuito de Render, y qué ocurre en Netlify al
  agotar los créditos: se leen en cada panel, no se prometen.
- El tiempo real de despertar.
