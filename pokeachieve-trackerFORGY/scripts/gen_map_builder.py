import json, re
from pathlib import Path
import ast

repo = Path(r"C:/Users/thefo/Documents/Codex/pokeachieve-tracker")
text = (repo / "scripts" / "pokemon.c").read_text(encoding="utf-8")

start = text.index("static const u16 sSpeciesToNationalPokedexNum")
brace_start = text.index("{", start)
brace_end = text.index("};", brace_start)
block = text[brace_start:brace_end]
symbols = re.findall(r"SPECIES_TO_NATIONAL\(([^)]+)\)", block)

py_text = (repo / "tracker_gui.py").read_text(encoding="utf-8")
module = ast.parse(py_text)
pokemon_names = None
for node in module.body:
    if isinstance(node, ast.ClassDef) and node.name == "PokemonMemoryReader":
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "POKEMON_NAMES":
                        pokemon_names = ast.literal_eval(stmt.value)
                        break
            if pokemon_names is not None:
                break
    if pokemon_names is not None:
        break
if pokemon_names is None:
    raise RuntimeError("POKEMON_NAMES not found")

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())

name_to_id = {norm(name): int(pid) for pid, name in pokemon_names.items()}

mapping = {}
unresolved = []
for internal_id, sym in enumerate(symbols, start=1):
    if sym.startswith("OLD_UNOWN_"):
        mapping[internal_id] = 201
        continue
    key = norm(sym.replace("_", " "))
    national_id = name_to_id.get(key)
    if national_id is None:
        unresolved.append((internal_id, sym, key))
        continue
    mapping[internal_id] = int(national_id)

mapping = {k: v for k, v in mapping.items() if 1 <= k <= 411}

out_path = repo / "gen3_internal_to_national.json"
out_path.write_text(json.dumps({str(k): int(v) for k, v in sorted(mapping.items())}, indent=2, sort_keys=True), encoding="utf-8")

print(f"symbols={len(symbols)} mapped={len(mapping)} unresolved={len(unresolved)}")
print("internal 332 ->", mapping.get(332))
print("internal 310 ->", mapping.get(310))
if unresolved:
    print("sample unresolved:", unresolved[:8])
