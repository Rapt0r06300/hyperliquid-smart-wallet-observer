#!/usr/bin/env python3
"""[Bloc 2/3/4] Generateur du registre MACHINE des taches + EVIDENCE, base des gates.

Scanne le repo REEL (src/ + tests/) et classe HONNETEMENT chaque code de tache (AUD-*, DATA-*, BUG-*) :
  - done_wired    : au moins un module cite le code, un test le couvre, ET le module a un APPELANT reel
                    (importe par un autre module hors tests) -> branche + teste.
  - coded_unwired : module + test mais AUCUN appelant (code mort potentiel).
  - coded_untested: module mais aucun test.
  - untraced      : aucun module ne cite le code (le concern peut exister ailleurs mais N'EST PAS
                    lie a l'ID de tache -> echoue la barre de tracabilite/preuve).

Le graphe d'imports resout les imports ABSOLUS (hl_observer.x) ET RELATIFS (from . / from .sub),
donc un adaptateur importe seulement en relatif compte quand meme comme branche.

N.B. 'done_wired' ne prouve PAS le runtime E2E ni le live : c'est le niveau STRUCTUREL. Le runtime/live
est trace separement (EVIDENCE/ + gate live_ready). 0 reseau, stdlib pure, deterministe.
"""
from __future__ import annotations

import ast
import json
import os
import sys


def task_codes():
    out = ["AUD-%03d" % i for i in range(1, 391)]
    out += ["DATA-%03d" % i for i in range(1, 121)]
    out += ["BUG-%03d" % i for i in range(1, 81)]
    return out


def _walk_py(root):
    acc = []
    for d, _, fs in os.walk(root):
        if "__pycache__" in d:
            continue
        for f in fs:
            if f.endswith(".py"):
                acc.append(os.path.join(d, f))
    return acc


def dotted_of(path, src_dir):
    rel = os.path.relpath(path, src_dir).replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def resolve_imports(path, dotted, text):
    """Retourne l'ensemble des cibles dottees importees par ce fichier (absolues + relatives resolues)."""
    targets = set()
    pkg = dotted.rsplit(".", 1)[0] if "." in dotted else dotted
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return targets
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("hl_observer"):
                    targets.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = pkg.split(".")
                up = node.level - 1
                base = base[: len(base) - up] if up else base
                prefix = ".".join(base)
                mod = (prefix + "." + node.module) if node.module else prefix
                targets.add(mod)
                for a in node.names:
                    targets.add(mod + "." + a.name)
            elif node.module and node.module.startswith("hl_observer"):
                targets.add(node.module)
                for a in node.names:
                    targets.add(node.module + "." + a.name)
    return targets


def main(root="."):
    src_dir = os.path.join(root, "src")
    tests_dir = os.path.join(root, "tests")
    src_files = _walk_py(src_dir)
    test_files = _walk_py(tests_dir)

    src_text = {p: open(p, encoding="utf-8", errors="replace").read() for p in src_files}
    test_text = {p: open(p, encoding="utf-8", errors="replace").read() for p in test_files}
    mod_of = {p: dotted_of(p, src_dir) for p in src_files}

    # graphe d'imports : edges importer_dotted -> target_dotted
    edges = []
    for p, t in src_text.items():
        for tgt in resolve_imports(p, mod_of[p], t):
            edges.append((mod_of[p], tgt))

    def has_caller(modname):
        for a, tgt in edges:
            if a == modname:
                continue
            if a.startswith(modname + "."):
                continue  # un sous-module qui importe son parent ne compte pas comme appelant externe
            if tgt == modname or tgt.startswith(modname + "."):
                return True
        return False

    caller_cache = {}

    def wired(modname):
        if modname not in caller_cache:
            caller_cache[modname] = has_caller(modname)
        return caller_cache[modname]

    rows = []
    tally = {"done_wired": 0, "coded_unwired": 0, "coded_untested": 0, "untraced": 0}
    for code in task_codes():
        mods = sorted(p for p in src_files if code in src_text[p])
        mods_dotted = sorted({mod_of[p] for p in mods})
        # teste si un test cite le code, ou importe un des modules citant le code
        tested = any(code in tt for tt in test_text.values())
        if not tested and mods_dotted:
            for tt in test_text.values():
                if any(md in tt for md in mods_dotted):
                    tested = True
                    break
        is_wired = any(wired(md) for md in mods_dotted)
        if not mods:
            status = "untraced"
        elif not tested:
            status = "coded_untested"
        elif not is_wired:
            status = "coded_unwired"
        else:
            status = "done_wired"
        tally[status] += 1
        rows.append({
            "code": code,
            "status": status,
            "wired": bool(is_wired),
            "tested": bool(tested),
            "n_modules": len(mods),
            "modules": [os.path.relpath(m, root).replace(os.sep, "/") for m in mods[:6]],
        })
    return rows, tally, {"src": len(src_files), "tests": len(test_files), "edges": len(edges)}


def write_outputs(root, rows, tally, meta):
    os.makedirs(os.path.join(root, "EVIDENCE"), exist_ok=True)
    with open(os.path.join(root, "CLAUDE_TASKS.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(root, "EVIDENCE", "scan_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"tally": tally, "meta": meta, "total": len(rows)}, f, indent=2, sort_keys=True)
    lines = ["# CLAUDE_TASKS_LATEST — registre machine (scan structurel)", "",
             "Scan REEL de src/ + tests/. `done_wired` = module + test + appelant reel (branche).",
             "Ne prouve PAS le runtime/live (trace a part). Regenerer : `python tools/claude_tasks_scan.py`.",
             "",
             "| statut | n |", "|---|---|"]
    for k in ("done_wired", "coded_unwired", "coded_untested", "untraced"):
        lines.append("| %s | %d |" % (k, tally[k]))
    lines += ["", "meta : %d modules, %d tests, %d edges d'import." % (meta["src"], meta["tests"], meta["edges"]), ""]
    with open(os.path.join(root, "CLAUDE_TASKS_LATEST.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    rows, tally, meta = main(root)
    write_outputs(root, rows, tally, meta)
    print("TALLY", json.dumps(tally))
    print("META", json.dumps(meta))
