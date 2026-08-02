"""[PORTABILITE item 3] Verrou du wheelhouse hors ligne : versions + SHA-256 de CHAQUE roue.

Le wheelhouse (`tools\\wheelhouse`) contient toutes les dépendances en `.whl` pour une installation
HORS LIGNE (portable_env.cmd force `PIP_NO_INDEX` + `PIP_FIND_LINKS` dès qu'il existe). Ce module
CALCULE et VÉRIFIE un verrou `WHEELHOUSE_LOCK.json` : nom + version + SHA-256 + taille de chaque roue.
Toute divergence (roue modifiée, manquante, ajoutée) est détectée — on n'installe jamais une dépendance
non attendue. Pur (hashlib/pathlib), 0 réseau, testable partout.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "hypersmart.wheelhouse_lock.v1"
# nom de roue : {distribution}-{version}-{python}-{abi}-{platform}.whl  (PEP 427)
_WHL = re.compile(r"^(?P<dist>.+?)-(?P<ver>[^-]+)-.+\.whl$", re.IGNORECASE)


def _sha256(chemin: Path, *, chunk: int = 1 << 20) -> tuple[str, int]:
    h = hashlib.sha256()
    taille = 0
    with chemin.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            taille += len(b)
    return h.hexdigest(), taille


def _nom_version(nom_fichier: str) -> tuple[str, str]:
    m = _WHL.match(nom_fichier)
    if not m:
        return nom_fichier, ""
    return m.group("dist").replace("_", "-").lower(), m.group("ver")


def construire_verrou(wheelhouse: str | Path) -> dict:
    """Verrou complet du wheelhouse : {schema, n, roues:{fichier:{dist,version,sha256,taille}}}."""
    wheelhouse = Path(wheelhouse)
    roues: dict[str, dict] = {}
    for whl in sorted(wheelhouse.glob("*.whl")):
        dist, ver = _nom_version(whl.name)
        sha, taille = _sha256(whl)
        roues[whl.name] = {"dist": dist, "version": ver, "sha256": sha, "taille": taille}
    empreinte = hashlib.sha256(
        json.dumps(roues, sort_keys=True).encode("utf-8")).hexdigest()
    return {"schema": SCHEMA, "n": len(roues), "empreinte": empreinte, "roues": roues}


def ecrire_verrou(wheelhouse: str | Path, sortie: str | Path) -> dict:
    verrou = construire_verrou(wheelhouse)
    Path(sortie).write_text(json.dumps(verrou, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
    return verrou


def verifier_verrou(wheelhouse: str | Path, verrou: str | Path | dict) -> dict:
    """Recalcule et compare au verrou. Rend {ok, verifiees, manquantes[], divergentes[], surplus[]}."""
    attendu = verrou if isinstance(verrou, dict) else json.loads(Path(verrou).read_text(encoding="utf-8"))
    attendu_roues = attendu.get("roues", {})
    actuel = construire_verrou(wheelhouse)["roues"]
    manquantes = [n for n in attendu_roues if n not in actuel]
    surplus = [n for n in actuel if n not in attendu_roues]
    divergentes = [n for n in attendu_roues if n in actuel
                   and (actuel[n]["sha256"] != attendu_roues[n].get("sha256")
                        or actuel[n]["taille"] != attendu_roues[n].get("taille"))]
    verifiees = sum(1 for n in attendu_roues if n in actuel and n not in divergentes)
    ok = not manquantes and not divergentes and not surplus
    return {"ok": ok, "verifiees": verifiees, "manquantes": sorted(manquantes),
            "divergentes": sorted(divergentes), "surplus": sorted(surplus)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="wheelhouse_lock",
                                 description="Verrou versions+SHA-256 du wheelhouse portable (item 3).")
    ap.add_argument("--wheelhouse", required=True)
    ap.add_argument("--ecrire", default="", help="chemin du WHEELHOUSE_LOCK.json a ecrire")
    ap.add_argument("--verifier", default="", help="verifie le wheelhouse contre ce verrou et sort")
    args = ap.parse_args(argv)
    if args.verifier:
        res = verifier_verrou(args.wheelhouse, args.verifier)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 4
    if args.ecrire:
        v = ecrire_verrou(args.wheelhouse, args.ecrire)
        print("WHEELHOUSE_LOCK ecrit : %d roue(s), empreinte %s" % (v["n"], v["empreinte"][:12]))
        return 0
    v = construire_verrou(args.wheelhouse)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0


__all__ = ["SCHEMA", "construire_verrou", "ecrire_verrou", "verifier_verrou", "main"]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
