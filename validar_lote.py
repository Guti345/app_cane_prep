import json, sys, glob
from jsonschema import validate

# Uso: python validar_lote.py private-data/lotes/econometria_01.json
# o varios a la vez: python validar_lote.py private-data/lotes/*.json
esquema = json.load(open("private-data/esquema_preguntas_schema.json", encoding="utf-8"))

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
