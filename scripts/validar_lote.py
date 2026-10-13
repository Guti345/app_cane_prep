import json, sys, glob
from pathlib import Path
from jsonschema import validate

# Uso, desde cualquier carpeta (con el entorno que tenga jsonschema, p. ej.
# backend/.venv):
#   python scripts/validar_lote.py private-data/lotes/econometria_01/econometria_01.json
#   python scripts/validar_lote.py "private-data/lotes/*/*.json"      (comillas: lo expande el script)
# Las rutas de los lotes se leen relativas a la carpeta desde donde se ejecuta;
# el esquema se busca siempre en <raiz del repo>/private-data/.
ESQUEMA = Path(__file__).resolve().parents[1] / "private-data" / "esquema_preguntas_schema.json"
esquema = json.load(open(ESQUEMA, encoding="utf-8"))

archivos = []
for a in sys.argv[1:]:
    archivos += glob.glob(a)

total = 0
for ruta in sorted(archivos):
    lote = json.load(open(ruta, encoding="utf-8"))
    validate(lote, esquema)
    ids = [q["id"] for q in lote["questions"]]
    assert len(ids) == len(set(ids)), "id duplicado en " + ruta
    total += len(ids)
    print("OK:", ruta, "-", len(ids), "preguntas,",
          len(lote["pending_questions"]), "pendientes")
print("TOTAL:", total, "preguntas")
