# Importador del banco de preguntas

`scripts/importar_banco.py` lee los lotes JSON de `private-data/lotes/`, aplica
las decisiones de curación y los carga en PostgreSQL **en una sola
transacción**. Las decisiones están en
[`scripts/curacion_2026-10-12.json`](../scripts/curacion_2026-10-12.json):
identifican preguntas por **área + número** y no contienen enunciados ni claves.

**Estado:** probado con el banco real (483 preguntas) en un PostgreSQL local y
cargado en `pruebas_cane` (2026-10-13). Contra el proyecto real solo se puede
ejecutar con el opt-in específico de la sección "Proyecto real"; no se ha
ejecutado.

## Qué garantiza

- La clave vive en `question_keys`, aparte; la tabla `questions` no tiene
  columna de respuesta.
- Toda pregunta activa lleva `verified_at` y `verified_basis`; ninguna activa
  queda sin ellos (el plan lo valida y la base lo exige: regla D5).
- Re-ejecutarlo **no cambia** el estado de preguntas existentes: solo inserta
  las nuevas y avisa de las que difieren.
- Todo o nada: si algo falla, no queda nada a medias.
- Se niega a operar contra el proyecto real, con o sin `--remoto`, salvo con el
  opt-in específico `--remoto --destino-real <referencia>` (ver "Proyecto real").
- Si las cuentas no cuadran con las esperadas del archivo de curación, no
  carga nada.

## Requisitos

- Entorno virtual del backend con `jsonschema` (está en
  `backend/requirements-dev.txt`): `pip install -r requirements-dev.txt`.
- `private-data/lotes/` con las carpetas `<lote>/<lote>.json` y
  `<lote>/assets/` y el esquema `private-data/esquema_preguntas_schema.json`.
- Para cargar: las tres migraciones aplicadas en el destino (la segunda añade
  las columnas de curación y la tercera la tabla de figuras).

## Uso

Desde la raíz del repositorio:

```powershell
# 1. Prueba en seco (por defecto). No abre ninguna conexión.
backend\.venv\Scripts\python scripts\importar_banco.py

# 2. Contra una base LOCAL. La cadena va en una variable de entorno, no como
#    argumento (no queda en el historial de la terminal). No la pegues en el chat.
$env:IMPORT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/postgres?sslmode=disable"
backend\.venv\Scripts\python scripts\importar_banco.py --aplicar

# 3. Contra pruebas_cane: --remoto es obligatorio; antes un ensayo (revierte).
$env:IMPORT_DATABASE_URL = "<cadena del proyecto de PRUEBAS>"
backend\.venv\Scripts\python scripts\importar_banco.py --aplicar --remoto --ensayo
backend\.venv\Scripts\python scripts\importar_banco.py --aplicar --remoto
```

| Opción | Efecto |
| --- | --- |
| *(ninguna)* | Prueba en seco: lee, valida, clasifica, imprime cuentas e informe. |
| `--aplicar` | Carga en la base de `IMPORT_DATABASE_URL`. |
| `--ensayo` | Con `--aplicar`: hace todo, comprueba los triggers y **revierte**. |
| `--remoto` | Permite un destino que no es `localhost`. |
| `--destino-real REF` | Opt-in para el proyecto real. `REF` debe ser la referencia del proyecto real y coincidir **exactamente** con la que lleva la cadena de conexión. Exige también `--remoto`. |
| `--sin-figuras` | No sube las imágenes (para destinos sin la tabla `question_assets`). El informe lo indica; una ejecución posterior sin la opción las completa. |
| `--forzar-estado` | Reaplica estado, motivo y verificación a preguntas ya existentes. |
| `--reporte RUTA` | Guarda el informe (usa `private-data/reportes/`, ignorado por Git). |

Códigos de salida: `0` bien; `1` falló la carga (se revirtió); `2` problemas en
los lotes o en la curación, o cuentas que no cuadran (no se carga nada).

## Reglas de clasificación

| Orden | Regla | Resultado |
| --- | --- | --- |
| 1 | Descartada en la curación | `discarded`, con motivo y `duplicate_of` |
| 2 | En una lista de inactivas o duplicada de otra | `inactive`; si es duplicada y no tiene motivo propio, `duplicada_de`; siempre registra `duplicate_of` |
| 3 | En `force_active` | `active`; se guarda `ready` y sin avisos, y los avisos de origen quedan en `review_note` |
| 4 | `ready` con clave | `active`, con `verified_at` = hora del import y `verified_basis` |
| 5 | Cualquier otra (p. ej. `needs_review` o sin clave) | `inactive` con motivo `revisar_no_clasificada` y aparece en el informe |

Las duplicadas se validan: misma área, se conserva el número menor y ambas deben
tener **la misma clave**; si no, el importador para.

## Estados en la base

`active` sigue siendo el único interruptor del motor de juego. El estado se
deduce así:

| Estado | Condición | Columnas relacionadas |
| --- | --- | --- |
| Activa | `active = true` | `question_keys.verified_at` y `verified_basis` obligatorios (D5) |
| Inactiva | `active = false` y `discarded = false` | `review_reason`; `duplicate_of` si aplica |
| Descartada | `discarded = true` (nunca activa) | `review_reason`, `duplicate_of`; el rastro evita reimportarla |

Motivos usados por el importador: `sin_clave`, `grafico_dudoso`,
`texto_dudoso`, `duplicada_de`, `revisar_no_clasificada`. El motivo es texto
libre: puedes añadir otros al corregir.

**Sobre `verified_by`.** La regla pedía `verified_by =
'decision_bloque_ready_2026-10-12'`, pero esa columna es una referencia a un
perfil (uuid) y se queda para una persona concreta. La base de la decisión en
bloque va en la columna nueva `verified_basis`, que es la que lleva ese valor.
Si prefieres un solo campo de texto, es un cambio pequeño en una migración
nueva; pídelo.

## Idempotencia

Una pregunta existente se reconoce por `(bank_id, source_id)`. Al re-ejecutar:

- **No existe:** se inserta con el estado del plan.
- **Existe:** no se toca nada. Si su contenido difiere del archivo se lista
  como *contenido distinto* (para cambiarlo hay que crear una revisión nueva;
  el importador no la crea); si su estado difiere del plan se lista como
  *estado distinto* (esperable tras tus correcciones en Supabase).
- **`--forzar-estado`:** reaplica el estado del plan a las existentes (activa,
  descartada, motivo, `duplicate_of`, y `verified_at` si pasa a activa y no lo
  tenía). Nunca cambia contenido. Úsalo solo si quieres volver al estado de la
  curación; revisa antes con `--ensayo`.

## Corregir preguntas desde Supabase

Cambiar solo la casilla `active` en el editor de tablas **a `false`** funciona.
**A `true` falla** si la clave no tiene `verified_at` (regla D5), y también si
la pregunta no está `ready` o tiene avisos. Para activar una pregunta revisada,
en el SQL Editor y en este orden (primero la clave):

```sql
UPDATE public.question_keys
   SET verified_at = now(), verified_basis = 'revision_manual_AAAA-MM-DD'
 WHERE question_id = (SELECT id FROM public.questions
                      WHERE source_id = 'cane-2026-econometria-004' AND revision = 1);

UPDATE public.questions
   SET review_status = 'ready', warnings = '[]'::jsonb,
       active = true, review_reason = NULL
 WHERE source_id = 'cane-2026-econometria-004' AND revision = 1;
```

Una pregunta ya usada en sesiones es inmutable en contenido y clave
(*"Versión usada: cree una revisión nueva"*); el estado editorial (`active`,
`discarded`, `review_reason`, `duplicate_of`, `review_note`, `review_status`,
`warnings`) sí se puede cambiar.

Consultas de control (solo lectura):

```sql
-- Cuentas por área y estado
SELECT area,
       count(*) FILTER (WHERE active)                         AS activas,
       count(*) FILTER (WHERE NOT active AND NOT discarded)   AS inactivas,
       count(*) FILTER (WHERE discarded)                      AS descartadas
FROM public.questions GROUP BY area ORDER BY area;

-- No activas sin motivo (esperado: ninguna)
SELECT area, source_number, source_id FROM public.questions
WHERE NOT active AND review_reason IS NULL ORDER BY area, source_number;

-- Activas con clave nula o sin verificación (esperado: ninguna)
SELECT q.source_id FROM public.questions q
JOIN public.question_keys k ON k.question_id = q.id
WHERE q.active AND (k.correct_option IS NULL OR k.verified_at IS NULL);
```

## Figuras (imágenes)

Las figuras de `assets/` se suben a `public.question_assets` (bytea) en la misma
transacción que las preguntas. Se sirven por un endpoint autenticado de FastAPI
(ver [`arquitectura.md`](arquitectura.md)); no hay Storage ni URLs públicas.

- Antes de cargar se valida cada archivo: existe, tiene extensión `png`, `jpg`
  o `webp`, su contenido corresponde a esa extensión (firma del archivo) y pesa
  entre 1 byte y 2 MiB. Un SVG o un archivo disfrazado se rechaza.
- Se guarda el `sha256` y el tipo MIME. Solo se suben las figuras con estado
  `available`.
- **Aditivo:** una figura que ya está no se reemplaza. Si el archivo cambió, se
  lista como *contenido distinto* y se deja como estaba (una figura de una
  pregunta ya usada en sesiones es inmutable, como su enunciado).
- Con las 483 preguntas son 14 figuras (785 186 bytes); 8 pertenecen a
  preguntas activas.

## Proyecto real

El proyecto real **no se carga con el flujo normal**: el importador lo rechaza aunque
se pase `--remoto`. Cargarlo exige el opt-in `--destino-real <referencia>`, que no es
un "permitir producción" genérico: lleva la referencia y se comprueba contra la cadena.

Cómo se identifica el destino (sin imprimir la cadena y sin aceptar coincidencias
parciales; la forma de las cadenas es la que documenta Supabase):

| Conexión | Dónde está la referencia |
| --- | --- |
| Directa | host `db.<referencia>.supabase.co` |
| Session pooler / Transaction pooler | usuario `<rol>.<referencia>` (el host del pooler es compartido) |

Se rechaza, con un mensaje sin la cadena, cuando:

- falta `--remoto`, o `--destino-real` no es una referencia de proyecto real autorizada;
- la cadena no nombra ningún proyecto (host ajeno, `localhost`, o la referencia solo
  aparece en la contraseña, el nombre de la base o como parte de otro host);
- el host y el usuario nombran proyectos distintos;
- la referencia de la cadena no coincide con `--destino-real` (p. ej. es la de pruebas).

No cambia nada más: sigue siendo una transacción, con `--ensayo` (rollback), sin
reemplazar lo existente y con la comprobación de cantidades. Primero el ensayo y,
solo si coincide con lo esperado, la carga:

```powershell
# La cadena del Session pooler del proyecto REAL va en la variable de entorno de ESTA
# terminal (tecleada o pegada por ti; no se imprime, no va en el chat ni en un archivo versionado).
$env:IMPORT_DATABASE_URL = "<cadena del Session pooler del proyecto real>"

backend\.venv\Scripts\python scripts\importar_banco.py --aplicar --remoto --destino-real <referencia del proyecto real> --ensayo
backend\.venv\Scripts\python scripts\importar_banco.py --aplicar --remoto --destino-real <referencia del proyecto real>
```

La variable de entorno tiene prioridad sobre `private-data/importador.env`, así que una
cadena de pruebas guardada ahí no se usa por descuido; y si se usara, el opt-in la
rechazaría por no coincidir. No uses `--forzar-estado` ni `--sin-figuras` para sortear
diferencias: si las cuentas no cuadran, el importador no carga nada y hay que revisar.

### Cadena del proyecto real: archivo aparte

El importador **no** tiene una opción para elegir otro archivo: `read_dsn` usa la variable de
entorno `IMPORT_DATABASE_URL` y, solo si no existe, `private-data/importador.env` (el de pruebas).
Para el real se usa un archivo local aparte, ignorado por Git (`.gitignore` cubre
`private-data/`), que **un bloque de PowerShell** carga en la variable de entorno de esa sesión y
limpia en un `finally`: `private-data/importador-real.env`, con una sola línea
`IMPORT_DATABASE_URL=<cadena del Session pooler del proyecto real>`. La cadena la escribe la
persona en ese archivo; nunca va en un comando, argumento ni en el bloque.

- Como la variable de entorno tiene prioridad, `importador.env` (pruebas) no se lee mientras la
  variable esté definida. Si por error faltara, el opt-in `--destino-real` rechazaría la cadena de
  pruebas por no coincidir con la referencia.
- El bloque (`docs/paso-manual-real-ensayo.txt`) aborta si la variable ya estaba definida, si el
  archivo no está ignorado, o si la cadena nombra pruebas u otro proyecto.
- El ensayo (`--ensayo`) escribe dentro de una transacción y la revierte; el informe va a
  `private-data/reportes/`. La carga definitiva es un paso distinto, con el mismo opt-in y sin
  `--ensayo`.
- Control posterior, de solo lectura: `docs/control-carga-real.sql` (valores esperados junto a
  cada recuento).

## Cadena de conexión

Se lee de la variable de entorno `IMPORT_DATABASE_URL` o, si no existe, de una
línea `IMPORT_DATABASE_URL=...` en `private-data/importador.env` (ignorado por
Git). El importador nunca la imprime y no la acepta como argumento.

## Orden recomendado contra `pruebas_cane`

1. ✔ *(2026-10-13)* `20261013034510_curacion_banco.sql` aplicada con la CLI
   desde la carpeta temporal vinculada a pruebas (ver
   [`supabase.md`](supabase.md)); historial local y remoto coinciden.
2. ✔ *(2026-10-13)* Limpiadas las 24 preguntas ficticias de
   [`prueba-backend-datos.sql`](prueba-backend-datos.sql) con intentos →
   sesiones → preguntas (las claves caen en cascada). Perfiles y equipos de
   prueba intactos.
3. ✔ *(2026-10-13)* Importado **sin figuras** (`--aplicar --remoto --ensayo
   --sin-figuras` y luego sin `--ensayo`): 483 / 427 activas / 55 inactivas /
   1 descartada, 483 filas en `question_keys`, las 427 activas con
   `verified_at` y `verified_basis`, ninguna no activa con `verified_at`, 15
   con `duplicate_of`. Segunda ejecución: 0 insertadas, 483 intactas.
4. ✔ *(2026-10-13)* `20261013044404_question_assets.sql` aplicada de la misma
   forma y figuras subidas con el importador sin `--sin-figuras` (ensayo y
   carga): 14 filas en `question_assets` (785 186 bytes) de 13 preguntas
   (8 activas con 1 figura; 5 no activas con 6, una con 2). Las 483
   preguntas conservan el mismo hash por fila antes y después. Segunda
   ejecución: 0 figuras nuevas, 14 existentes.
   `--sin-figuras` no deja ningún marcador: `questions.assets` ya trae el
   `ref` y el estado desde la carga; solo faltaban las filas de bytes.

## Pruebas

`backend/tests/integration/test_importador.py` (36 pruebas): clasificación,
errores de curación, protección del destino, lectura de lotes, y carga contra
PostgreSQL con las migraciones reales (activa sin `verified_at` rechazada,
re-ejecución idempotente, cambios manuales respetados, `--forzar-estado`,
ensayo que revierte, congelado de versiones usadas, figuras: firma y tamaño,
subida con hash, sin reemplazo, tabla sin acceso para `anon`/`authenticated`,
inmutabilidad de figuras usadas y entrega solo de preguntas ya emitidas). Se
comprobó con mutaciones que cada regla clave rompe alguna prueba.

Se ejecutan con el resto: `cd backend; python -m pytest`.

## Límites

- No hay modo para reemplazar una figura ya subida; habría que crear una
  revisión nueva de la pregunta.
- `pending_questions` de los lotes se cuenta pero no se importa (hoy hay 0).
- No hay modo para publicar una revisión nueva de una pregunta ya cargada.
- La protección contra el proyecto real compara la referencia del proyecto con
  la cadena de conexión; no es un control de acceso de la base.
