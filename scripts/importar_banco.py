"""Importador del banco de preguntas CANE.

Lee los lotes JSON de `private-data/lotes/`, los valida contra el esquema,
aplica las decisiones de curación de `scripts/curacion_*.json` y, solo si se
pide, los carga en PostgreSQL en UNA transacción.

Uso (desde la raíz del repositorio, con el entorno virtual del backend):

    # 1. Prueba en seco (por defecto): no abre ninguna conexión.
    backend/.venv/Scripts/python scripts/importar_banco.py

    # 2. Cargar (la cadena de conexión va en IMPORT_DATABASE_URL, nunca como argumento).
    backend/.venv/Scripts/python scripts/importar_banco.py --aplicar
    #    --ensayo  hace todo igual pero revierte al final.
    #    --remoto  obligatorio si el destino no es localhost (p. ej. pruebas_cane).
    #    --destino-real REF  opt-in para el proyecto real: REF debe ser su referencia y
    #                        coincidir exactamente con la que lleva la cadena de conexión.
    #    --forzar-estado  reaplica estado/motivo/verificación a preguntas YA existentes.

Reglas que garantiza:
- La clave vive en `question_keys`; nunca viaja con la pregunta.
- Una pregunta activa siempre lleva `verified_at` y `verified_basis`.
- Re-ejecutar NO cambia el estado de preguntas existentes (salvo --forzar-estado):
  solo inserta las nuevas y avisa de las que difieren.
- Se niega a operar contra el proyecto real salvo con `--remoto --destino-real <ref>`,
  y solo si la referencia verificada en la cadena coincide exactamente (ver `check_target`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOTES = ROOT / "private-data" / "lotes"
DEFAULT_SCHEMA = ROOT / "private-data" / "esquema_preguntas_schema.json"
DEFAULT_CURATION = ROOT / "scripts" / "curacion_2026-10-12.json"

AREAS = ("econometria", "microeconomia", "macroeconomia", "historia_pensamiento")
REASON_DUPLICATE = "duplicada_de"
REASON_UNCLASSIFIED = "revisar_no_clasificada"
DSN_ENV = "IMPORT_DATABASE_URL"
DSN_FILE = ROOT / "private-data" / "importador.env"  # una línea: IMPORT_DATABASE_URL=...
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Proyecto real de producción: el importador se niega a tocarlo, con o sin --remoto,
# salvo con el opt-in específico `--remoto --destino-real <esta referencia>`.
# (La referencia ya es pública: forma parte de la URL de Supabase que lleva el frontend.)
BLOCKED_PROJECT_REFS = ("lzzyuxploolyqgitjtdu",)

# Referencia de proyecto de Supabase: 20 letras minúsculas.
_REF = r"[a-z]{20}"
_DIRECT_HOST = re.compile(rf"^db\.({_REF})\.supabase\.co$")
_POOLER_USER = re.compile(rf"^[A-Za-z_][A-Za-z0-9_]*\.({_REF})$")


class ImportPlanError(Exception):
    """El plan no es válido. `problems` lista TODOS los problemas encontrados."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(problems))


# --- 1. lectura y validación de los lotes --------------------------------------------


def load_batches(lotes_dir: Path, schema: dict[str, Any]) -> tuple[list[dict], int, list[str]]:
    """Devuelve (preguntas, pendientes, problemas). No lanza por problemas de datos."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    questions: list[dict] = []
    pending = 0
    problems: list[str] = []
    files = sorted(lotes_dir.glob("*/*.json"))
    if not files:
        problems.append(f"No hay lotes JSON en {lotes_dir} (se espera <lote>/<lote>.json)")
    for path in files:
        batch = path.parent.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{batch}: no se pudo leer el JSON ({exc})")
            continue
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        for err in errors[:5]:
            where = "/".join(str(p) for p in err.absolute_path) or "(raíz)"
            problems.append(f"{batch}: esquema en {where}: {err.message[:120]}")
        if errors:
            continue
        pending += len(data["pending_questions"])
        for q in data["questions"]:
            q = dict(q, _bank_id=data["bank_id"], _batch=batch, _dir=str(path.parent))
            problems.extend(_check_question(q, path.parent))
            questions.append(q)
    seen_id: dict[str, str] = {}
    seen_key: dict[tuple, str] = {}
    for q in questions:
        key = (q["_bank_id"], q["area"], q["source_number"])
        for table, k, what in ((seen_id, q["id"], "id"), (seen_key, key, "area+número")):
            if k in table:
                problems.append(
                    f"{what} repetido: {k} en {table[k]} y {q['_batch']}"
                )
            table[k] = q["_batch"]
    return questions, pending, problems


def _check_question(q: dict, batch_dir: Path) -> list[str]:
    tag = f"{q['_batch']}: {q['area']} {q['source_number']}"
    problems: list[str] = []
    expected_id = f"{q['_bank_id']}-{q['area']}-{q['source_number']:03d}"
    if q["id"] != expected_id:
        problems.append(f"{tag}: id {q['id']!r} no coincide con {expected_id!r}")
    labels = [o["label"] for o in q["options"]]
    if labels != list("ABCDE"[: len(labels)]):
        problems.append(f"{tag}: etiquetas {labels} no son A, B, C… en orden")
    if q["correct_option"] is not None and q["correct_option"] not in labels:
        problems.append(f"{tag}: la clave {q['correct_option']} no está entre las opciones")
    for asset in q["assets"]:
        if asset["status"] != "available":
            continue
        path = batch_dir / asset["ref"]
        if not path.is_file():
            problems.append(f"{tag}: falta el archivo del recurso {asset['ref']}")
            continue
        problem = check_image_file(path)
        if problem:
            problems.append(f"{tag}: recurso {asset['ref']}: {problem}")
    return problems


# Debe coincidir con los límites de public.question_assets.
MAX_ASSET_BYTES = 2 * 1024 * 1024
_SIGNATURES = {
    ".png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ".webp": ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def check_image_file(path: Path) -> str | None:
    """None si el archivo es una imagen válida para la base; si no, el motivo."""
    kind = _SIGNATURES.get(path.suffix.lower())
    if kind is None:
        return f"extensión {path.suffix!r} no admitida"
    size = path.stat().st_size
    if size == 0 or size > MAX_ASSET_BYTES:
        return f"tamaño {size} fuera de 1..{MAX_ASSET_BYTES} bytes"
    with path.open("rb") as fh:
        head = fh.read(16)
    if not kind[1](head):
        return "el contenido no corresponde a su extensión"
    return None


def asset_mime(ref: str) -> str:
    return _SIGNATURES[Path(ref).suffix.lower()][0]


# --- 2. plan: clasificación de cada pregunta (función pura) ---------------------------


@dataclass(frozen=True)
class Planned:
    q: dict
    state: str  # active | inactive | discarded
    reason: str | None
    duplicate_of: str | None  # source_id de la pregunta que se conserva
    note: str | None
    review_status: str  # el que se guardará
    warnings: list
    verified: bool

    @property
    def source_id(self) -> str:
        return self.q["id"]

    @property
    def area(self) -> str:
        return self.q["area"]

    @property
    def number(self) -> int:
        return self.q["source_number"]


def build_plan(questions: list[dict], curation: dict[str, Any]) -> list[Planned]:
    """Aplica la curación. Reúne todos los problemas antes de fallar."""
    by_key = {(q["area"], q["source_number"]): q for q in questions}
    problems: list[str] = []

    def exists(area: str, number: int, where: str) -> bool:
        if (area, number) in by_key:
            return True
        problems.append(f"{where}: {area} {number} no existe en los lotes")
        return False

    reason_of: dict[tuple[str, int], str] = {}
    for block in curation["inactive"]:
        for area, numbers in block["questions"].items():
            for n in numbers:
                if not exists(area, n, f"inactiva/{block['reason']}"):
                    continue
                if (area, n) in reason_of:
                    problems.append(f"{area} {n}: aparece en dos listas de inactivas")
                reason_of[(area, n)] = block["reason"]

    forced: dict[tuple[str, int], str] = {}
    for item in curation["force_active"]:
        key = (item["area"], item["number"])
        if not exists(*key, "force_active"):
            continue
        if by_key[key]["correct_option"] is None:
            problems.append(f"{key[0]} {key[1]}: force_active sin clave en la fuente")
        if key in reason_of:
            problems.append(f"{key[0]} {key[1]}: está en force_active y en una lista de inactivas")
        forced[key] = item["note"]

    discarded: dict[tuple[str, int], tuple[str, str]] = {}
    for item in curation["discarded"]:
        key, keep = (item["area"], item["number"]), (item["area"], item["of"])
        if exists(*key, "descartada") and exists(*keep, "descartada/of"):
            discarded[key] = (item["reason"], by_key[keep]["id"])

    dup_of: dict[tuple[str, int], tuple[str, int]] = {}
    for item in curation["duplicates"]:
        key, keep = (item["area"], item["number"]), (item["area"], item["of"])
        if not (exists(*key, "duplicada") and exists(*keep, "duplicada/of")):
            continue
        if keep[1] >= key[1]:
            problems.append(f"{key[0]} {key[1]}: se conserva la de número menor, no la {keep[1]}")
        a, b = by_key[key]["correct_option"], by_key[keep]["correct_option"]
        if a is None or b is None or a != b:
            problems.append(
                f"{key[0]} {key[1]} y {keep[1]}: no comparten clave ({a} / {b}); no son duplicadas"
            )
        if key in dup_of:
            problems.append(f"{key[0]} {key[1]}: duplicada de dos preguntas")
        dup_of[key] = keep

    if problems:
        raise ImportPlanError(problems)

    plan: list[Planned] = []
    for q in questions:
        key = (q["area"], q["source_number"])
        status, warnings = q["review_status"], q["warnings"]
        state, reason, parent, note = "active", None, None, None
        if key in discarded:
            state, (reason, parent) = "discarded", discarded[key]
        elif key in reason_of or key in dup_of:
            state = "inactive"
            reason = reason_of.get(key, REASON_DUPLICATE)
            if key in dup_of:
                parent = by_key[dup_of[key]]["id"]
        elif key in forced:
            status, warnings = "ready", []
            note = (
                f"{forced[key]} Estado de origen: {q['review_status']}. "
                f"Avisos de origen: {json.dumps(q['warnings'], ensure_ascii=False)}"
            )
        elif q["review_status"] != "ready" or q["correct_option"] is None:
            state, reason = "inactive", REASON_UNCLASSIFIED
        plan.append(
            Planned(
                q=q, state=state, reason=reason, duplicate_of=parent, note=note,
                review_status=status, warnings=warnings, verified=state == "active",
            )
        )
    validate_plan(plan)
    return plan


def validate_plan(plan: list[Planned]) -> None:
    """Invariantes que la base también exige; aquí fallan antes y con mejor mensaje."""
    problems: list[str] = []
    ids = {p.source_id for p in plan}
    for p in plan:
        tag = f"{p.area} {p.number}"
        if p.state == "active":
            if not p.verified:
                problems.append(f"{tag}: activa sin verified_at")
            if p.review_status != "ready" or p.warnings:
                problems.append(f"{tag}: activa pero no ready o con avisos")
            if p.q["correct_option"] is None:
                problems.append(f"{tag}: activa sin clave")
            if any(a["status"] != "available" for a in p.q["assets"]):
                problems.append(f"{tag}: activa con recurso pendiente")
        else:
            if p.verified:
                problems.append(f"{tag}: no activa pero marcada como verificada")
            if not p.reason:
                problems.append(f"{tag}: {p.state} sin motivo")
        if p.duplicate_of is not None and p.duplicate_of not in ids:
            problems.append(f"{tag}: duplicate_of {p.duplicate_of} no existe")
    if problems:
        raise ImportPlanError(problems)


@dataclass
class Summary:
    total: int
    by_state: Counter
    by_reason: Counter  # solo inactivas
    by_area: dict[str, Counter]
    unclassified: list[Planned] = field(default_factory=list)
    groups_without_active: list[tuple[str, list[str]]] = field(default_factory=list)


def summarize(plan: list[Planned]) -> Summary:
    by_id = {p.source_id: p for p in plan}
    groups: dict[str, list[str]] = {}
    for p in plan:
        if p.duplicate_of:
            groups.setdefault(p.duplicate_of, []).append(p.source_id)
    without_active = []
    for keep, dups in sorted(groups.items()):
        members = [keep, *dups]
        if not any(by_id[m].state == "active" for m in members):
            without_active.append((keep, sorted(dups)))
    return Summary(
        total=len(plan),
        by_state=Counter(p.state for p in plan),
        by_reason=Counter(p.reason for p in plan if p.state == "inactive"),
        by_area={a: Counter(p.state for p in plan if p.area == a) for a in AREAS},
        unclassified=[p for p in plan if p.reason == REASON_UNCLASSIFIED],
        groups_without_active=without_active,
    )


def check_expected(summary: Summary, expected: dict[str, Any]) -> list[str]:
    """Compara con las cuentas esperadas por Antonio. Lista vacía = cuadran."""
    got = {
        "total": summary.total,
        "active": summary.by_state["active"],
        "inactive": summary.by_state["inactive"],
        "discarded": summary.by_state["discarded"],
    }
    diffs = [
        f"{name}: esperado {expected[name]}, resultado {value}"
        for name, value in got.items()
        if value != expected[name]
    ]
    reasons = expected["inactive_by_reason"]
    for reason in sorted(set(reasons) | set(summary.by_reason)):
        want, have = reasons.get(reason, 0), summary.by_reason[reason]
        if want != have:
            diffs.append(f"inactive_by_reason.{reason}: esperado {want}, resultado {have}")
    return diffs


# --- 3. destino: protección ------------------------------------------------------------


def read_dsn(env: dict[str, str] | None = None, file: Path = DSN_FILE) -> str | None:
    """La cadena de conexión, de la variable de entorno o de un archivo local ignorado.

    Nunca se imprime ni se acepta como argumento (quedaría en el historial).
    """
    env = os.environ if env is None else env
    if env.get(DSN_ENV):
        return env[DSN_ENV]
    if file.is_file():
        for line in file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == DSN_ENV and value.strip():
                return value.strip().strip("\"'")
    return None


def identify_project_ref(dsn: str) -> str | None:
    """Referencia del proyecto de Supabase que nombra la cadena, o None si no la nombra.

    Dos formas, las que documenta Supabase:
    - conexión directa: host `db.<ref>.supabase.co` (el usuario es `postgres`);
    - pooler: el usuario es `<rol>.<ref>` y el host es compartido (`*.pooler.supabase.com`).

    Si el host y el usuario nombran referencias distintas, la identidad es
    contradictoria y se rechaza (`ValueError`). No hay coincidencias parciales: ni la
    contraseña, ni el nombre de la base, ni un fragmento del host cuentan.
    """
    from psycopg.conninfo import conninfo_to_dict

    try:
        params = conninfo_to_dict(dsn)
    except Exception as exc:  # cadena mal formada: sin eco de su contenido
        raise ValueError("cadena de conexión ilegible") from exc
    found: set[str] = set()
    host = (params.get("host") or "").lower()
    if (m := _DIRECT_HOST.match(host)):
        found.add(m.group(1))
    if (m := _POOLER_USER.match(params.get("user") or "")):
        found.add(m.group(1))
    if len(found) > 1:
        raise ValueError("el host y el usuario nombran proyectos distintos")
    return next(iter(found), None)


def check_target(dsn: str, allow_remote: bool, real_ref: str | None = None) -> str:
    """Devuelve 'local', 'remoto' o 'real'. Nunca incluye la cadena en los mensajes.

    El proyecto real solo se admite con el opt-in específico: `real_ref` (el valor de
    `--destino-real`) debe ser una referencia de BLOCKED_PROJECT_REFS, la cadena debe
    nombrar exactamente esa referencia (host directo o usuario del pooler) y además hay
    que pasar `--remoto`. Cualquier duda (identidad no verificable, otra referencia,
    referencia solo "contenida" en la cadena) se rechaza.
    """
    from psycopg.conninfo import conninfo_to_dict

    if real_ref is not None:
        if real_ref not in BLOCKED_PROJECT_REFS:
            raise SystemExit(
                "RECHAZADO: --destino-real no corresponde a ningún proyecto real autorizado."
            )
        if not allow_remote:
            raise SystemExit("RECHAZADO: el proyecto real exige también --remoto.")
        try:
            actual = identify_project_ref(dsn)
        except ValueError:
            raise SystemExit(
                "RECHAZADO: no se pudo verificar a qué proyecto apunta la cadena de conexión."
            ) from None
        if actual is None:
            raise SystemExit(
                "RECHAZADO: la cadena no nombra un proyecto (host db.<ref>.supabase.co o "
                "usuario <rol>.<ref>); no se puede verificar el destino."
            )
        if actual != real_ref:
            raise SystemExit(
                "RECHAZADO: la referencia de la cadena no coincide con --destino-real."
            )
        return "real"

    for ref in BLOCKED_PROJECT_REFS:
        if ref in dsn:
            raise SystemExit(
                "RECHAZADO: el destino es el proyecto real. Para cargarlo hace falta el "
                "opt-in específico (--remoto --destino-real <referencia>)."
            )
    host = conninfo_to_dict(dsn).get("host") or "localhost"
    if host in LOCAL_HOSTS or host.startswith("/"):
        return "local"
    if not allow_remote:
        raise SystemExit(
            "RECHAZADO: el destino no es localhost. Si es el proyecto de pruebas, "
            "repite con --remoto."
        )
    return "remoto"


# --- 4. aplicación a PostgreSQL ----------------------------------------------------------

_COUNTS = """
    SELECT area, count(*) AS total, count(*) FILTER (WHERE active) AS active,
           count(*) FILTER (WHERE discarded) AS discarded
    FROM public.questions WHERE bank_id = %s GROUP BY area
"""
_EXISTING = """
    SELECT DISTINCT ON (q.source_id)
           q.id, q.source_id, q.area, q.source_number, q.source_pages, q.statement_md,
           q.options, q.assets, q.active, q.discarded, q.review_reason, k.verified_at
    FROM public.questions q LEFT JOIN public.question_keys k ON k.question_id = q.id
    WHERE q.bank_id = %s ORDER BY q.source_id, q.revision DESC
"""
_INSERT_Q = """
    INSERT INTO public.questions
      (id, bank_id, source_id, revision, area, source_number, source_pages, source_year,
       source_edition, source_phase, statement_md, options, assets, warnings,
       review_status, active, discarded, review_reason, duplicate_of, review_note)
    VALUES (%(id)s, %(bank_id)s, %(source_id)s, 1, %(area)s, %(number)s, %(pages)s::integer[],
       %(year)s, %(edition)s, %(phase)s, %(statement)s, %(options)s, %(assets)s, %(warnings)s,
       %(status)s, %(active)s, %(discarded)s, %(reason)s, %(duplicate_of)s, %(note)s)
"""
_INSERT_K = """
    INSERT INTO public.question_keys (question_id, correct_option, verified_at, verified_basis)
    VALUES (%s, %s, %s, %s)
"""
_FORCE_Q = """
    UPDATE public.questions SET review_status = %s, warnings = %s, active = %s,
           discarded = %s, review_reason = %s, duplicate_of = %s, review_note = %s
    WHERE id = %s
"""
_ASSETS_OF = """
    SELECT question_id, ref, sha256 FROM public.question_assets WHERE question_id = ANY(%s)
"""
_INSERT_ASSET = """
    INSERT INTO public.question_assets (question_id, ref, mime_type, sha256, data)
    VALUES (%s, %s, %s, %s, %s)
"""
_FORCE_K = """
    UPDATE public.question_keys SET verified_at = %s, verified_basis = %s
    WHERE question_id = %s AND verified_at IS NULL
"""


@dataclass
class ApplyResult:
    before: dict[str, int]
    after: dict[str, int]
    inserted: int = 0
    existing_skipped: int = 0
    content_drift: list[str] = field(default_factory=list)
    state_differs: list[str] = field(default_factory=list)  # existentes con otro estado
    forced: list[str] = field(default_factory=list)
    rolled_back: bool = False
    assets_inserted: int = 0
    assets_existing: int = 0
    assets_bytes: int = 0
    assets_changed: list[str] = field(default_factory=list)  # mismo ref, otro contenido
    assets_skipped: int = 0  # figuras disponibles que no se subieron (--sin-figuras)


def _content_signature(statement: str, options: Any, assets: Any, pages: Any) -> str:
    return json.dumps([statement, options, assets, list(pages)], sort_keys=True, ensure_ascii=False)


def _db_counts(conn: Any, bank_id: str) -> dict[str, int]:
    rows = conn.execute(_COUNTS, (bank_id,)).fetchall()
    total = sum(r["total"] for r in rows)
    active = sum(r["active"] for r in rows)
    discarded = sum(r["discarded"] for r in rows)
    return {"total": total, "active": active, "discarded": discarded,
            "inactive": total - active - discarded}


def apply_plan(
    conn: Any,
    plan: list[Planned],
    verified_basis: str,
    *,
    force_state: bool = False,
    dry_run: bool = False,
    upload_figures: bool = True,
) -> ApplyResult:
    """Escribe el plan en UNA transacción. No hace commit: lo hace `conn.transaction()`.

    Con `dry_run` ejecuta todo y revierte al final (ensayo).
    """
    from psycopg import Rollback
    from psycopg.types.json import Jsonb

    bank_ids = {p.q["_bank_id"] for p in plan}
    if len(bank_ids) != 1:
        raise ImportPlanError([f"Se esperaba un solo bank_id, hay {sorted(bank_ids)}"])
    (bank_id,) = bank_ids
    result = ApplyResult(before=_db_counts(conn, bank_id), after={})

    with conn.transaction():
        now = conn.execute("SELECT now() AS t").fetchone()["t"]
        existing = {r["source_id"]: r for r in conn.execute(_EXISTING, (bank_id,)).fetchall()}
        new_q: list[dict] = []
        new_k: list[tuple] = []
        question_ids: dict[str, Any] = {}
        for p in plan:
            row = existing.get(p.source_id)
            if row is not None:
                question_ids[p.source_id] = row["id"]
            if row is None:
                qid = uuid.uuid4()
                question_ids[p.source_id] = qid
                q = p.q
                new_q.append({
                    "id": qid, "bank_id": bank_id, "source_id": p.source_id, "area": p.area,
                    "number": p.number, "pages": q["source_pages"], "year": q["source_year"],
                    "edition": q["source_edition"], "phase": q["source_phase"],
                    "statement": q["statement_md"], "options": Jsonb(q["options"]),
                    "assets": Jsonb(q["assets"]), "warnings": Jsonb(p.warnings),
                    "status": p.review_status, "active": p.state == "active",
                    "discarded": p.state == "discarded", "reason": p.reason,
                    "duplicate_of": p.duplicate_of, "note": p.note,
                })
                new_k.append((qid, q["correct_option"],
                              now if p.verified else None,
                              verified_basis if p.verified else None))
                continue
            # La pregunta ya existe: no se toca su estado ni su verificación.
            result.existing_skipped += 1
            same = _content_signature(
                row["statement_md"], row["options"], row["assets"], row["source_pages"]
            ) == _content_signature(
                p.q["statement_md"], p.q["options"], p.q["assets"], p.q["source_pages"]
            )
            if not same:
                result.content_drift.append(p.source_id)
            db_state = "discarded" if row["discarded"] else "active" if row["active"] else "inactive"
            if db_state != p.state:
                result.state_differs.append(f"{p.source_id}: base={db_state}, plan={p.state}")
                if force_state:
                    conn.execute(_FORCE_Q, (
                        p.review_status, Jsonb(p.warnings), p.state == "active",
                        p.state == "discarded", p.reason, p.duplicate_of, p.note, row["id"],
                    ))
                    if p.verified:
                        conn.execute(_FORCE_K, (now, verified_basis, row["id"]))
                    result.forced.append(p.source_id)
        if new_q:
            with conn.cursor() as cur:
                cur.executemany(_INSERT_Q, new_q)
                cur.executemany(_INSERT_K, new_k)
        result.inserted = len(new_q)
        if upload_figures:
            _upload_assets(conn, plan, question_ids, result)
        else:
            result.assets_skipped = sum(
                1 for p in plan for a in p.q["assets"] if a["status"] == "available"
            )

        # Evalúa ya los triggers diferidos (clave, ready, D5) para fallar antes del commit.
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        result.after = _db_counts(conn, bank_id)
        if not force_state:
            added = Counter(
                "active" if r["active"] else "discarded" if r["discarded"] else "inactive"
                for r in new_q
            )
            for state in ("active", "inactive", "discarded"):
                want = result.before[state] + added[state]
                if result.after[state] != want:
                    raise ImportPlanError(
                        [f"Cuenta inesperada tras insertar ({state}): {result.after[state]} != {want}"]
                    )
        if dry_run:
            result.rolled_back = True
            raise Rollback
    return result


def _upload_assets(conn: Any, plan: list[Planned], question_ids: dict[str, Any],
                   result: ApplyResult) -> None:
    """Sube las figuras que aún no están. Aditivo: nunca reemplaza una existente."""
    wanted = [
        (question_ids[p.source_id], a["ref"], Path(p.q["_dir"]) / a["ref"], p.source_id)
        for p in plan for a in p.q["assets"] if a["status"] == "available"
    ]
    if not wanted:
        return
    have = {
        (r["question_id"], r["ref"]): r["sha256"]
        for r in conn.execute(_ASSETS_OF, ([w[0] for w in wanted],)).fetchall()
    }
    rows = []
    for qid, ref, path, source_id in wanted:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if (qid, ref) in have:
            result.assets_existing += 1
            if have[(qid, ref)] != digest:
                result.assets_changed.append(f"{source_id}: {ref}")
            continue
        rows.append((qid, ref, asset_mime(ref), digest, data))
        result.assets_bytes += len(data)
    if rows:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_ASSET, rows)
    result.assets_inserted = len(rows)


# --- 5. informe ---------------------------------------------------------------------------


def render_report(
    plan: list[Planned], summary: Summary, expected_diffs: list[str],
    *, batches: int, pending: int, result: ApplyResult | None = None,
) -> str:
    out: list[str] = []
    w = out.append
    w(f"Lotes leídos: {batches}   preguntas: {summary.total}   pendientes: {pending}")
    w("")
    w("CUENTAS")
    s = summary.by_state
    w(f"  total {summary.total}  activas {s['active']}  inactivas {s['inactive']}  descartadas {s['discarded']}")
    w("  inactivas por motivo: " + ", ".join(f"{r}={n}" for r, n in sorted(summary.by_reason.items())))
    w("  contra lo esperado: " + ("CUADRA" if not expected_diffs else "NO CUADRA"))
    for d in expected_diffs:
        w(f"    - {d}")
    w("")
    w(f"  {'área':<22}{'total':>6}{'activas':>9}{'inactivas':>11}{'descartadas':>13}")
    for area in AREAS:
        c = summary.by_area[area]
        w(f"  {area:<22}{sum(c.values()):>6}{c['active']:>9}{c['inactive']:>11}{c['discarded']:>13}")
    w("")
    w("INACTIVAS (área número  motivo  [duplicada de])")
    for p in sorted((p for p in plan if p.state == "inactive"), key=lambda p: (p.reason, p.area, p.number)):
        extra = f"  de {p.duplicate_of}" if p.duplicate_of else ""
        w(f"  {p.area:<22}{p.number:>4}  {p.reason}{extra}")
    w("")
    w("DESCARTADAS")
    for p in plan:
        if p.state == "discarded":
            w(f"  {p.area:<22}{p.number:>4}  {p.reason}  de {p.duplicate_of}")
    w("")
    w("ACTIVADAS A MANO (estado de origen distinto de ready)")
    for p in plan:
        if p.state == "active" and p.q["review_status"] != "ready":
            w(f"  {p.area:<22}{p.number:>4}  origen={p.q['review_status']}")
    w("")
    w("DUPLICADAS SIN NINGUNA VERSIÓN ACTIVA (ni la conservada)")
    for keep, dups in summary.groups_without_active:
        w(f"  {keep}  <-  {', '.join(dups)}")
    if not summary.groups_without_active:
        w("  (ninguna)")
    w("")
    w("NO CLASIFICADAS (revisar_no_clasificada)")
    for p in summary.unclassified:
        w(f"  {p.area:<22}{p.number:>4}  origen={p.q['review_status']} clave={p.q['correct_option']}")
    if not summary.unclassified:
        w("  (ninguna)")
    if result is not None:
        w("")
        w("BASE DE DATOS" + ("  (ENSAYO: revertido)" if result.rolled_back else ""))
        for label, counts in (("antes", result.before), ("después", result.after)):
            w(f"  {label:<8} total {counts['total']}  activas {counts['active']}  "
              f"inactivas {counts['inactive']}  descartadas {counts['discarded']}")
        w(f"  insertadas {result.inserted}   ya existentes (sin tocar) {result.existing_skipped}")
        w(f"  contenido distinto al archivo: {len(result.content_drift)}"
          + (f" -> {', '.join(result.content_drift[:10])}" if result.content_drift else ""))
        w(f"  estado distinto al plan: {len(result.state_differs)}")
        for line in result.state_differs[:20]:
            w(f"    {line}")
        w(f"  forzadas: {len(result.forced)}")
        if result.assets_skipped:
            w(f"  recursos: NO subidos ({result.assets_skipped} figuras disponibles; --sin-figuras)")
        else:
            w(f"  recursos: insertados {result.assets_inserted} ({result.assets_bytes} bytes), "
              f"ya existentes {result.assets_existing}, con contenido distinto {len(result.assets_changed)}")
        for line in result.assets_changed:
            w(f"    {line}")
    return "\n".join(out)


# --- 6. línea de comandos -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lotes", type=Path, default=DEFAULT_LOTES)
    ap.add_argument("--esquema", type=Path, default=DEFAULT_SCHEMA)
    ap.add_argument("--curacion", type=Path, default=DEFAULT_CURATION)
    ap.add_argument("--aplicar", action="store_true", help="carga en la base (por defecto: en seco)")
    ap.add_argument("--ensayo", action="store_true", help="con --aplicar: ejecuta y revierte")
    ap.add_argument("--remoto", action="store_true", help="permite un destino que no es localhost")
    ap.add_argument("--destino-real", metavar="REF", default=None,
                    help="opt-in para el proyecto real: su referencia, que debe coincidir "
                         "exactamente con la de la cadena de conexión (exige --remoto)")
    ap.add_argument("--sin-figuras", action="store_true",
                    help="no sube las imágenes (para destinos sin la tabla question_assets)")
    ap.add_argument("--forzar-estado", action="store_true",
                    help="reaplica estado y verificación a preguntas ya existentes")
    ap.add_argument("--reporte", type=Path, help="guarda el informe en este archivo")
    args = ap.parse_args(argv)

    schema = json.loads(args.esquema.read_text(encoding="utf-8"))
    curation = json.loads(args.curacion.read_text(encoding="utf-8"))
    questions, pending, problems = load_batches(args.lotes, schema)
    if problems:
        print("LOTES CON PROBLEMAS (no se importa nada):")
        for p in problems:
            print("  -", p)
        return 2
    try:
        plan = build_plan(questions, curation)
    except ImportPlanError as exc:
        print("CURACIÓN CON PROBLEMAS (no se importa nada):")
        for p in exc.problems:
            print("  -", p)
        return 2
    summary = summarize(plan)
    diffs = check_expected(summary, curation["expected"])
    batches = len({q["_batch"] for q in questions})

    result = None
    exit_code = 0
    if diffs:
        exit_code = 2
    elif args.aplicar:
        dsn = read_dsn()
        if not dsn:
            print(f"Falta {DSN_ENV}: defínela como variable de entorno o en una línea de "
                  f"{DSN_FILE.relative_to(ROOT)} (ignorado por Git).")
            return 2
        target = check_target(dsn, args.remoto, args.destino_real)
        import psycopg
        from psycopg.rows import dict_row

        shown = "proyecto REAL (referencia verificada)" if target == "real" else target
        print(f"Destino: {shown}. Transacción única{' (ensayo, se revierte)' if args.ensayo else ''}.")
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(dsn)
        params.setdefault("sslmode", "require")
        try:
            conn_ctx = psycopg.connect(make_conninfo(**params), row_factory=dict_row,
                                       prepare_threshold=None, connect_timeout=15)
        except psycopg.Error as exc:
            # Sin el texto del error: puede incluir host y usuario del destino.
            print(f"No se pudo conectar al destino ({type(exc).__name__}, "
                  f"sqlstate {getattr(exc, 'sqlstate', None)}). Nada se modificó.")
            return 1
        with conn_ctx as conn:
            try:
                result = apply_plan(conn, plan, curation["verified_basis"],
                                    force_state=args.forzar_estado, dry_run=args.ensayo,
                                    upload_figures=not args.sin_figuras)
            except ImportPlanError as exc:
                print("FALLÓ y se revirtió todo:", str(exc).splitlines()[0][:300])
                return 1
            except psycopg.Error as exc:
                # El mensaje de la base puede nombrar objetos; no incluye la cadena de conexión.
                print(f"FALLÓ y se revirtió todo ({type(exc).__name__}):",
                      str(exc).splitlines()[0][:200])
                return 1

    report = render_report(plan, summary, diffs, batches=batches, pending=pending, result=result)
    print(report)
    if args.reporte:
        args.reporte.parent.mkdir(parents=True, exist_ok=True)
        args.reporte.write_text(report + "\n", encoding="utf-8")
    if diffs:
        print("\nLas cuentas no cuadran con lo esperado: no se carga nada. Revisa la curación.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
