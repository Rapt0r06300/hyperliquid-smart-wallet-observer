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

SCHEMA = "hypersmart.wheelhouse_lock.v2"
TARGET = "cp314-win_amd64"
_LOCK_LINE = re.compile(
    r"^(?P<dist>[A-Za-z0-9_.-]+)==(?P<ver>[^\s]+)\s+--hash=sha256:(?P<sha>[0-9a-fA-F]{64})$"
)


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
    if not nom_fichier.lower().endswith(".whl"):
        return nom_fichier, ""
    morceaux = nom_fichier[:-4].rsplit("-", 3)
    if len(morceaux) != 4 or "-" not in morceaux[0]:
        return nom_fichier, ""
    prefixe, _python, _abi, _plateforme = morceaux
    dist, version = prefixe.split("-", 1)
    return _normaliser_dist(dist), version


def _normaliser_dist(nom: str) -> str:
    return re.sub(r"[-_.]+", "-", nom).lower()


def tags_roue(nom_fichier: str) -> tuple[str, str, str]:
    morceaux = nom_fichier[:-4].rsplit("-", 3) if nom_fichier.lower().endswith(".whl") else []
    if len(morceaux) != 4:
        return "", "", ""
    return morceaux[1], morceaux[2], morceaux[3]


def roue_windows_x64_compatible(nom_fichier: str) -> bool:
    python_tag, abi_tag, platform_tag = tags_roue(nom_fichier)
    platforms = set(platform_tag.lower().split("."))
    pythons = set(python_tag.lower().split("."))
    if platforms == {"any"}:
        return any(tag.startswith("py3") for tag in pythons) and abi_tag.lower() == "none"
    if "win_amd64" not in platforms:
        return False
    return (
        "cp314" in pythons
        or any(tag.startswith("cp3") and abi_tag.lower() == "abi3" for tag in pythons)
        or (any(tag.startswith("py3") for tag in pythons) and abi_tag.lower() == "none")
    )


def lire_requirements_verrouilles(chemin: str | Path) -> dict[str, dict[str, str]]:
    attendu: dict[str, dict[str, str]] = {}
    for numero, brut in enumerate(Path(chemin).read_text(encoding="utf-8-sig").splitlines(), 1):
        ligne = brut.strip()
        if not ligne or ligne.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(ligne)
        if not match:
            raise ValueError(f"requirement non verrouille ligne {numero}: {ligne}")
        dist = _normaliser_dist(match.group("dist"))
        if dist in attendu:
            raise ValueError(f"distribution dupliquee: {dist}")
        attendu[dist] = {"version": match.group("ver"), "sha256": match.group("sha").lower()}
    if not attendu:
        raise ValueError("requirements lock vide")
    return attendu


def construire_verrou(wheelhouse: str | Path) -> dict:
    """Verrou complet du wheelhouse : {schema, n, roues:{fichier:{dist,version,sha256,taille}}}."""
    wheelhouse = Path(wheelhouse)
    roues: dict[str, dict] = {}
    incompatibles: list[str] = []
    interdits = sorted(
        p.name for p in wheelhouse.iterdir()
        if p.is_file() and p.name != "WHEELHOUSE_LOCK.json" and p.suffix.lower() != ".whl"
    ) if wheelhouse.is_dir() else []
    for whl in sorted(wheelhouse.glob("*.whl")):
        dist, ver = _nom_version(whl.name)
        sha, taille = _sha256(whl)
        compatible = roue_windows_x64_compatible(whl.name)
        if not compatible:
            incompatibles.append(whl.name)
        roues[whl.name] = {
            "dist": dist, "version": ver, "sha256": sha, "taille": taille,
            "compatible_windows_x64": compatible,
        }
    empreinte = hashlib.sha256(
        json.dumps(roues, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA, "target": TARGET, "n": len(roues), "empreinte": empreinte,
        "incompatibles": incompatibles, "fichiers_interdits": interdits, "roues": roues,
    }


def ecrire_verrou(wheelhouse: str | Path, sortie: str | Path) -> dict:
    verrou = construire_verrou(wheelhouse)
    Path(sortie).write_text(json.dumps(verrou, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
    return verrou


def verifier_verrou(
    wheelhouse: str | Path,
    verrou: str | Path | dict,
    requirements: str | Path | None = None,
) -> dict:
    """Recalcule et compare au verrou. Rend {ok, verifiees, manquantes[], divergentes[], surplus[]}."""
    attendu = verrou if isinstance(verrou, dict) else json.loads(Path(verrou).read_text(encoding="utf-8"))
    attendu_roues = attendu.get("roues", {})
    construit = construire_verrou(wheelhouse)
    actuel = construit["roues"]
    manquantes = [n for n in attendu_roues if n not in actuel]
    surplus = [n for n in actuel if n not in attendu_roues]
    divergentes = [n for n in attendu_roues if n in actuel
                   and (actuel[n]["sha256"] != attendu_roues[n].get("sha256")
                        or actuel[n]["taille"] != attendu_roues[n].get("taille"))]
    verifiees = sum(1 for n in attendu_roues if n in actuel and n not in divergentes)
    requirements_manquants: list[str] = []
    requirements_divergents: list[str] = []
    requirements_surplus: list[str] = []
    if requirements is not None:
        exigences = lire_requirements_verrouilles(requirements)
        par_dist = {meta["dist"]: meta for meta in actuel.values()}
        requirements_manquants = sorted(set(exigences) - set(par_dist))
        requirements_surplus = sorted(set(par_dist) - set(exigences))
        requirements_divergents = sorted(
            dist for dist in set(exigences) & set(par_dist)
            if par_dist[dist]["version"] != exigences[dist]["version"]
            or par_dist[dist]["sha256"] != exigences[dist]["sha256"]
        )
    ok = not (
        manquantes or divergentes or surplus or construit["incompatibles"]
        or construit["fichiers_interdits"] or requirements_manquants
        or requirements_divergents or requirements_surplus
    )
    return {"ok": ok, "verifiees": verifiees, "manquantes": sorted(manquantes),
            "divergentes": sorted(divergentes), "surplus": sorted(surplus),
            "incompatibles": construit["incompatibles"],
            "fichiers_interdits": construit["fichiers_interdits"],
            "requirements_manquants": requirements_manquants,
            "requirements_divergents": requirements_divergents,
            "requirements_surplus": requirements_surplus}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="wheelhouse_lock",
                                 description="Verrou versions+SHA-256 du wheelhouse portable (item 3).")
    ap.add_argument("--wheelhouse", required=True)
    ap.add_argument("--ecrire", default="", help="chemin du WHEELHOUSE_LOCK.json a ecrire")
    ap.add_argument("--verifier", default="", help="verifie le wheelhouse contre ce verrou et sort")
    ap.add_argument("--requirements", default="", help="lock package==version --hash a recouper")
    args = ap.parse_args(argv)
    if args.verifier:
        res = verifier_verrou(args.wheelhouse, args.verifier, args.requirements or None)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 4
    if args.ecrire:
        v = ecrire_verrou(args.wheelhouse, args.ecrire)
        print("WHEELHOUSE_LOCK ecrit : %d roue(s), empreinte %s" % (v["n"], v["empreinte"][:12]))
        return 0
    v = construire_verrou(args.wheelhouse)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "SCHEMA", "TARGET", "construire_verrou", "ecrire_verrou", "verifier_verrou",
    "lire_requirements_verrouilles", "roue_windows_x64_compatible", "main",
]


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
