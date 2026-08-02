"""[RELEASE item 14] Verdict UNIQUE `RELEASE_READY=true/false`, fail-closed.

Agrege toutes les portes d'une vraie release portable Windows. RELEASE_READY reste FALSE tant qu'une
seule porte n'est pas prouvee verte :
  - Python + DLL + wheels REELLEMENT embarques (tools\\python\\python.exe + python*.dll + wheelhouse
    verrouille) ;
  - aucun module/collecteur runtime manquant (ils s'importent tous) ;
  - manifeste + hashes presents et coherents ;
  - lock du wheelhouse verifie ;
  - tests verts (entree fournie par la CI) ;
  - CI du HEAD verte (entree) ;
  - test hermetique Windows passe (entree) ;
  - zero ecriture hors du dossier (entree du test hermetique).

Les portes verifiables ICI (embed, modules, manifeste, lock) sont calculees directement. Les portes qui
exigent une PREUVE externe (tests, CI, run hermetique Windows) sont des ENTREES qui valent False par
defaut — donc RELEASE_READY est False sur un checkout Linux sans embed, HONNETEMENT. Pur, 0 reseau.
"""
from __future__ import annotations

import json
from pathlib import Path


def _gate(nom: str, ok: bool, detail: str) -> dict:
    return {"gate": nom, "ok": bool(ok), "detail": detail}


def _embed_present(root: Path) -> dict:
    """Python embarque REELLEMENT present : python.exe + au moins une python*.dll a cote."""
    for rel in ("tools/python", "portable_runtime/python"):
        d = root / rel
        exe = d / "python.exe"
        if exe.is_file():
            dlls = list(d.glob("python*.dll"))
            if dlls:
                return _gate("python_embarque", True, "%s/python.exe + %d DLL" % (rel, len(dlls)))
            return _gate("python_embarque", False, "%s/python.exe sans python*.dll" % rel)
    return _gate("python_embarque", False, "tools/python/python.exe absent (embed non construit)")


def _wheelhouse_ok(root: Path) -> dict:
    wh = root / "tools" / "wheelhouse"
    lock = wh / "WHEELHOUSE_LOCK.json"
    if not wh.is_dir() or not list(wh.glob("*.whl")):
        return _gate("wheelhouse", False, "wheelhouse absent ou vide")
    if not lock.is_file():
        return _gate("wheelhouse", False, "WHEELHOUSE_LOCK.json absent")
    verifier_verrou = _charger_verifier_verrou(root)
    if verifier_verrou is None:
        return _gate("wheelhouse", False, "wheelhouse_lock introuvable")
    try:
        res = verifier_verrou(wh, lock)
    except Exception as exc:  # noqa: BLE001
        return _gate("wheelhouse", False, "verrou wheelhouse illisible : %s" % exc)
    return _gate("wheelhouse", bool(res.get("ok")),
                 "verrou %s (%d verifiees)" % ("OK" if res.get("ok") else "DIVERGENT", res.get("verifiees", 0)))


def _charger_verifier_verrou(root: Path):
    """tools/ est normalement sur PYTHONPATH ; sinon on charge le module depuis le fichier."""
    try:
        from wheelhouse_lock import verifier_verrou  # type: ignore
        return verifier_verrou
    except Exception:  # noqa: BLE001
        pass
    p = root / "tools" / "wheelhouse_lock.py"
    if not p.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("whl_lock", str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        return mod.verifier_verrou
    except Exception:  # noqa: BLE001
        return None


def _manifeste_ok(root: Path) -> dict:
    p = root / "PORTABLE_MANIFEST.json"
    if not p.is_file():
        return _gate("manifeste", False, "PORTABLE_MANIFEST.json absent")
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _gate("manifeste", False, "manifeste illisible : %s" % exc)
    a_hashes = isinstance(m.get("fichiers"), dict) and len(m["fichiers"]) > 0
    a_empreinte = bool(m.get("empreinte_globale"))
    return _gate("manifeste", a_hashes and a_empreinte,
                 "hashes=%s empreinte=%s" % (a_hashes, a_empreinte))


def _modules_ok(root: Path, importateur=None) -> dict:
    try:
        from hl_observer.ops.premier_lancement import verifier_modules_runtime
        r = verifier_modules_runtime(importateur=importateur)
        return _gate("modules_runtime", r["statut"] == "OK", r["detail"])
    except Exception as exc:  # noqa: BLE001
        return _gate("modules_runtime", False, "verif modules impossible : %s" % exc)


def evaluer_release(root: str | Path, *, tests_verts: bool = False, ci_verte: bool = False,
                    hermetique_ok: bool = False, aucune_ecriture_externe: bool = False,
                    importateur=None) -> dict:
    """Verdict unique. RELEASE_READY = ET logique de toutes les portes. Fail-closed : les preuves
    externes (tests/CI/hermetique/ecritures) valent False par defaut."""
    root = Path(root)
    gates = [
        _embed_present(root),
        _wheelhouse_ok(root),
        _manifeste_ok(root),
        _modules_ok(root, importateur=importateur),
        _gate("tests_verts", bool(tests_verts), "fourni par la CI"),
        _gate("ci_head_verte", bool(ci_verte), "fourni par la CI"),
        _gate("test_hermetique_windows", bool(hermetique_ok), "run archive hors ligne sur Windows propre"),
        _gate("zero_ecriture_externe", bool(aucune_ecriture_externe), "prouve par le test hermetique"),
    ]
    manquants = [g["gate"] for g in gates if not g["ok"]]
    return {"RELEASE_READY": not manquants, "manquants": manquants, "gates": gates}


def formater(verdict: dict) -> str:
    lignes = ["RELEASE_READY = %s" % ("true" if verdict["RELEASE_READY"] else "false")]
    for g in verdict["gates"]:
        lignes.append("  [%s] %-26s %s" % ("OK" if g["ok"] else "  ", g["gate"], g["detail"]))
    if verdict["manquants"]:
        lignes.append("  -> bloque par : %s" % ", ".join(verdict["manquants"]))
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from hl_observer.portabilite import racine_projet
    ap = argparse.ArgumentParser(prog="release_ready",
                                 description="Verdict unique RELEASE_READY (item 14), fail-closed.")
    ap.add_argument("--racine", default=None)
    ap.add_argument("--tests-verts", action="store_true")
    ap.add_argument("--ci-verte", action="store_true")
    ap.add_argument("--hermetique-ok", action="store_true")
    ap.add_argument("--aucune-ecriture-externe", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    racine = Path(args.racine) if args.racine else racine_projet(Path(__file__))
    v = evaluer_release(racine, tests_verts=args.tests_verts, ci_verte=args.ci_verte,
                        hermetique_ok=args.hermetique_ok,
                        aucune_ecriture_externe=args.aucune_ecriture_externe)
    print(json.dumps(v, ensure_ascii=False, indent=2) if args.json else formater(v))
    return 0 if v["RELEASE_READY"] else 1


__all__ = ["evaluer_release", "formater", "main"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
