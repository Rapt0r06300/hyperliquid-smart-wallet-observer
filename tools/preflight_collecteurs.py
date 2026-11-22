r"""Les collecteurs REQUIS demarreraient-ils ? Verifie sans rien demarrer.

POURQUOI (22/11/2026). Le plan economique nomme les collecteurs a allumer pour que la famille
`copy_vault` puisse etre prouvee. Au feu vert de l'operateur, une panne triviale -- un script
deplace, un import casse par une dependance montee de version, un fichier de configuration
absent -- ne doit pas se decouvrir a trois heures du matin, apres que la fenetre de collecte a
commence a courir.

Le cas d'ecole est documente dans le depot : `extra_headers` a ete RETIRE de `websockets` 14+ et
remonte jusqu'a `BaseEventLoop.create_connection()`, qui leve `TypeError`. Le site d'appel etant
dans un `while True`, le collecteur Gate reessayait **a l'infini sur une erreur permanente**.
Rien ne l'aurait annonce avant le demarrage ; un import suffit a le voir.

CE QUE CE PREFLIGHT FAIT, et rien de plus :

1. le `script` du registre existe-t-il sur le disque ?
2. compile-t-il (`py_compile`) ? Une erreur de syntaxe tue le processus immediatement.
3. ses IMPORTS se resolvent-ils ? On charge le module dans un sous-processus isole, SANS
   arguments et SANS appeler `main()` : un script correctement garde par
   `if __name__ == "__main__":` n'execute alors aucune collecte.
4. ses fichiers de configuration declares sont-ils presents et lisibles ?

CE QU'IL NE FAIT PAS. Aucune requete reseau, aucune ecriture, aucun processus de collecte. Il ne
prouve donc PAS qu'un collecteur collectera : il prouve qu'il ne mourra pas AVANT d'essayer.
C'est une borne inferieure, et elle est dite comme telle.

⚠️ Si un module se met a collecter DES L'IMPORT, le delai le coupe et c'est signale comme un
defaut : un collecteur doit garder son point d'entree.

LECTURE SEULE. PAPER.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

#: Les configurations dont un collecteur a besoin pour ne pas tourner a vide. Mesure du 19/11 :
#: les lanes collectaient 0 parce que `config/copy_vault_leaders.json` manquait.
CONFIGS_REQUISES: dict[str, tuple[str, ...]] = {
    "userfills-live": ("config/copy_vault_leaders.json",),
    "userfills-poll": ("config/copy_vault_leaders.json",),
    "scorer-vaults": (),
    "vault-collector": (),
    "carnet-collector": (),
    "copy-vault-checkpoints": (),
    "backfill-fills": (),
    "backfill-candles-vaults": (),
}

#: Un import ne doit pas durer : au-dela, le module FAIT quelque chose au chargement.
DELAI_IMPORT_S = 60


def collecteurs_requis() -> tuple[str, ...]:
    """Les noms exiges par le plan, lus dans le contrat et non recopies ici."""
    from hl_observer.simulation.copy_vault_collection_contract import (
        COPY_VAULT_REQUIRED_COLLECTORS,
    )
    return tuple(COPY_VAULT_REQUIRED_COLLECTORS)


def _registre() -> dict[str, dict]:
    import hl_observer.ops.collecteur_registry as reg

    tous: dict[str, dict] = {}
    for nom_attribut in dir(reg):
        if not nom_attribut.isupper():
            continue
        valeur = getattr(reg, nom_attribut)
        if isinstance(valeur, (list, tuple)):
            for entree in valeur:
                if isinstance(entree, dict) and entree.get("nom"):
                    tous.setdefault(str(entree["nom"]), entree)
    return tous


def verifier_un(nom: str, entree: dict | None, racine: pathlib.Path) -> dict:
    """Le verdict pour UN collecteur. `None` d'entree = inconnu du registre, pas « OK »."""
    bilan: dict[str, object] = {"collecteur": nom, "motifs": []}
    motifs: list[str] = bilan["motifs"]          # type: ignore[assignment]
    if entree is None:
        bilan["verdict"] = "INCONNU_DU_REGISTRE"
        motifs.append("aucune entree de registre : le plan exige un nom que personne ne declare")
        return bilan

    script = str(entree.get("script") or "").strip()
    bilan["script"] = script
    if not script:
        bilan["verdict"] = "SANS_SCRIPT"
        motifs.append("l'entree de registre ne nomme aucun script")
        return bilan

    chemin = racine / script
    if not chemin.is_file():
        bilan["verdict"] = "SCRIPT_ABSENT"
        motifs.append(f"introuvable : {script}")
        return bilan

    compile_ = subprocess.run(
        [sys.executable, "-m", "py_compile", str(chemin)],
        capture_output=True, text=True, cwd=racine, timeout=DELAI_IMPORT_S,
    )
    if compile_.returncode != 0:
        bilan["verdict"] = "NE_COMPILE_PAS"
        motifs.append((compile_.stderr or "").strip()[-300:])
        return bilan

    # Charger le module SANS arguments et SANS appeler main() : un script garde par
    # `if __name__ == "__main__":` n'execute alors aucune collecte.
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('_preflight', r'{chemin}')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['_preflight'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "print('IMPORTS_OK')\n"
    )
    try:
        issue = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            capture_output=True, text=True, cwd=racine, timeout=DELAI_IMPORT_S,
            env={**_env_sans_bruit(), "PYTHONPATH": str(racine / "src")},
        )
    except subprocess.TimeoutExpired:
        bilan["verdict"] = "AGIT_DES_L_IMPORT"
        motifs.append(f"l'import n'a pas rendu en {DELAI_IMPORT_S} s : le module fait quelque "
                      "chose au chargement (un collecteur doit garder son point d'entree)")
        return bilan
    if "IMPORTS_OK" not in (issue.stdout or ""):
        bilan["verdict"] = "IMPORTS_CASSES"
        motifs.append((issue.stderr or "").strip()[-400:])
        return bilan

    manquantes = [c for c in CONFIGS_REQUISES.get(nom, ()) if not (racine / c).is_file()]
    if manquantes:
        bilan["verdict"] = "CONFIG_ABSENTE"
        motifs.extend(f"configuration absente : {c}" for c in manquantes)
        return bilan

    bilan["verdict"] = "DEMARRERAIT"
    return bilan


def _env_sans_bruit() -> dict[str, str]:
    import os

    garde = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT", "WINDIR",
             "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMDATA")
    return {k: v for k, v in os.environ.items() if k.upper() in garde}


PROFILS = ("requis", "copy-vault-seul", "tous")


def collecteurs_du_profil(profil: str = "requis") -> tuple[str, ...]:
    """Les collecteurs a verifier. `requis` = le contrat (8) ; `copy-vault-seul` = le profil allege
    (13) ; `tous` = la liste complete du lanceur de campagne (20). Avant le 22/11/2026 seuls les 8
    requis etaient verifies : les 12 autres pouvaient mourir au demarrage sans que rien ne le dise."""
    if profil == "requis":
        return collecteurs_requis()
    if profil == "copy-vault-seul":
        import collecteurs_exploitation

        return collecteurs_exploitation.noms_copy_vault_seul()
    if profil == "tous":
        import watch_economic_collectors

        return tuple(watch_economic_collectors.DEFAULT_NAMES)
    raise ValueError(f"profil inconnu : {profil!r} ; attendus : {PROFILS}")


def preflight(racine: pathlib.Path | None = None, *, profil: str = "requis") -> dict:
    racine = (racine or RACINE).resolve()
    registre = _registre()
    lignes = [verifier_un(nom, registre.get(nom), racine) for nom in collecteurs_du_profil(profil)]
    pretes = [l for l in lignes if l["verdict"] == "DEMARRERAIT"]
    return {
        "collecteurs_exiges": len(lignes),
        "demarreraient": len(pretes),
        "bloques": [l for l in lignes if l["verdict"] != "DEMARRERAIT"],
        "detail": lignes,
        "verdict": "TOUS_PRETS" if len(pretes) == len(lignes) else "AU_MOINS_UN_BLOQUE",
        "ce_que_ca_ne_prouve_pas": (
            "qu'un collecteur COLLECTERA : seulement qu'il ne mourra pas avant d'essayer "
            "(aucune requete reseau n'a ete faite)"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--json", action="store_true")
    p.add_argument("--profil", default="requis", choices=PROFILS)
    args = p.parse_args(argv)
    bilan = preflight(pathlib.Path(args.racine), profil=args.profil)
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=1))
        return 0 if bilan["verdict"] == "TOUS_PRETS" else 3
    print("  PREFLIGHT DES COLLECTEURS REQUIS — verifie sans rien demarrer")
    print("  " + "=" * 70)
    for ligne in bilan["detail"]:
        marque = "OK  " if ligne["verdict"] == "DEMARRERAIT" else "!!  "
        print(f"  {marque}{str(ligne['collecteur']):<26} {ligne['verdict']}")
        for motif in ligne["motifs"]:                       # type: ignore[union-attr]
            print(f"         {motif}")
    print("  " + "-" * 70)
    print(f"  {bilan['demarreraient']}/{bilan['collecteurs_exiges']} demarreraient"
          f"   ->  {bilan['verdict']}")
    print(f"  ce que ca ne prouve PAS : {bilan['ce_que_ca_ne_prouve_pas']}")
    return 0 if bilan["verdict"] == "TOUS_PRETS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
