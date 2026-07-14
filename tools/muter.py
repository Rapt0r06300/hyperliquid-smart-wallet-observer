"""IDEA-93 — LE RUNNER DE MUTATION. Casse le code exprès, et regarde si les tests s'en rendent
compte (2026-07-13).

    « Un garde-fou qui ne peut pas echouer ne garde rien. »

USAGE (Windows) : MUTER.cmd
  -> data/reports/mutation_score.json  +  mutation.txt

CE QU'IL FAIT, POUR CHAQUE MUTANT :
  1. ecrit le fichier MUTE a la place de l'original (sauvegarde faite avant) ;
  2. relance UN SOUS-ENSEMBLE CIBLE de tests (ceux qui touchent ce module) ;
  3. restaure l'original -- TOUJOURS, meme si pytest plante (try/finally).

  test ROUGE  -> mutant TUE       -> les tests gardaient quelque chose. Bien.
  test VERT   -> mutant SURVIVANT -> **personne ne garde cette ligne.**

⚠️ SECURITE DU DISQUE : on restaure dans un `finally`, et on verifie le contenu apres coup.
Un runner de mutation qui laisserait un fichier MUTE dans `src/` serait la pire chose qu'on
puisse faire a ce projet. Un test verifie ce contrat (`test_le_runner_restaure_TOUJOURS`).

Aucun ordre reel : on mute du code, jamais un ordre.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from sous_processus_isole import creationflags  # noqa: E402

from hl_observer.testing.mutation import (  # noqa: E402
    Mutant,
    ResultatMutation,
    generer_mutants,
    verdict_global,
)

# ---------------------------------------------------------------------------------------------
# LES CIBLES. On ne mute PAS tout le projet : 3 500 tests x N mutants = des heures.
# On mute LE CHEMIN QUI DECIDE -- celui ou un bug coute de l'argent (paper) et ou on a
# DEJA trouve des bugs. Chaque cible cite les tests qui sont censes la garder.
# ---------------------------------------------------------------------------------------------
# ⚠️ `test_trous_trouves_par_mutation.py` est dans TOUTES les listes : c'est le fichier qui
#    BOUCHE les trous que ce meme outil a trouves. L'oublier ferait re-signaler des survivants
#    deja tues -- un outil qui ne voit pas ses propres correctifs ment aussi surement qu'un outil
#    qui les invente.
_BOUCHES = "tests/test_trous_trouves_par_mutation.py"

CIBLES: list[tuple[str, list[str]]] = [
    (
        "src/hl_observer/funding/carry_liquidation_risk.py",       # le bug `>` de #588
        ["tests/test_carry_liquidation_risk.py", "tests/test_delta_neutral_carry.py", _BOUCHES],
    ),
    (
        "src/hl_observer/agent/dead_zones.py",                     # le mot-cle mort du 13/07
        ["tests/test_zones_mortes_entree_mesuree.py",
         "tests/test_dead_zones_ne_sautodesarme_pas.py",
         "tests/test_self_improving_agent.py", _BOUCHES],
    ),
    (
        "src/hl_observer/edge/edge_calculator.py",                 # l'edge net apres couts
        # 🚩 IL N'Y A PAS DE `test_edge_calculator.py`. Le moteur d'edge -- LE calcul qui autorise
        # ou refuse une entree -- n'a pas de fichier de test a son nom. Ses tests sont EPARPILLES.
        # C'est deja un resultat : *le module le plus critique du bot n'a pas de gardien nomme.*
        ["tests/test_v9_quant_core.py", "tests/test_edge_source_q1.py",
         "tests/test_edge_vient_de_la_table.py", "tests/test_copy_edge_must_be_empirical.py",
         _BOUCHES],
    ),
    (
        "src/hl_observer/funding/funding_carry_economics.py",      # le verrou de jambe nue
        ["tests/test_funding_carry_economics.py", _BOUCHES],
    ),
]


def _tests_existants(chemins: list[str]) -> list[str]:
    return [p for p in chemins if (RACINE / p).exists()]


def _lancer(tests: list[str], timeout: int = 240) -> bool:
    """True si les tests PASSENT (donc mutant SURVIVANT).

    🚩 `creationflags=CREATE_NEW_PROCESS_GROUP` N'EST PAS UN DETAIL -- et ce n'est pas moi qui l'ai
    vu : c'est **l'invariant `test_outils_isoles_du_ctrl_c` qui a attrape MON outil** des sa 1re
    execution. Sans ce drapeau, un Ctrl-C emis par le pytest fils remonte a TOUTE la console et
    **tue la session parente** (cause racine de #600 : `os.kill(pid, 0)` EST un Ctrl-C sous
    Windows). Un runner de mutation lance des CENTAINES de pytest : sans isolation, il se
    suiciderait au premier.

    *Un invariant qui attrape le code de celui qui l'a ecrit est un invariant qui marche.*
    """
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
            cwd=str(RACINE),
            capture_output=True,
            timeout=timeout,
            creationflags=creationflags(),
        )
    except subprocess.TimeoutExpired:
        return False          # un mutant qui fait boucler = attrape (le temps EST un signal)
    return r.returncode == 0


def muter_fichier(rel: str, tests: list[str], *, maximum: int, verbeux: bool) -> ResultatMutation:
    chemin = RACINE / rel
    res = ResultatMutation(fichier=rel)
    if not chemin.exists():
        return res
    origine = chemin.read_text(encoding="utf-8")
    tests = _tests_existants(tests)
    if not tests:
        print("  [SKIP] %s : aucun test associe -- rien ne peut le garder." % rel)
        return res

    mutants: list[Mutant] = generer_mutants(origine, fichier=rel, maximum=maximum)
    print("  %s : %d mutants, tests = %s" % (rel, len(mutants), ", ".join(tests)))

    for i, m in enumerate(mutants, 1):
        try:
            chemin.write_text(m.code, encoding="utf-8")
            survit = _lancer(tests)
        except Exception:                                   # noqa: BLE001
            res.invalides += 1
            continue
        finally:
            # 🔴 LE CONTRAT : on restaure TOUJOURS. Un src/ laisse mute serait catastrophique.
            chemin.write_text(origine, encoding="utf-8")

        if survit:
            res.survivants.append(m)
            print("    [%3d/%3d] SURVIVANT  %s" % (i, len(mutants), m.description))
        else:
            res.tues += 1
            if verbeux:
                print("    [%3d/%3d] tue        %s" % (i, len(mutants), m.description))

    # verification paranoiaque : le fichier est-il bien revenu a l'original ?
    if chemin.read_text(encoding="utf-8") != origine:
        raise SystemExit("🔴 FICHIER NON RESTAURE : %s -- ARRET IMMEDIAT." % rel)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Mutation testing (IDEA-93). Aucun ordre reel.")
    ap.add_argument("--max-par-fichier", type=int, default=40)
    ap.add_argument("--plancher", type=float, default=0.0,
                    help="cliquet. 0.0 = on MESURE d'abord, on exige ensuite.")
    ap.add_argument("--verbeux", action="store_true")
    a = ap.parse_args()

    print("=" * 92)
    print("  MUTATION TESTING -- « un garde-fou qui ne peut pas echouer ne garde rien »")
    print("  On CASSE le code expres. Si les tests restent VERTS, ils ne gardaient rien.")
    print("=" * 92)

    t0 = time.time()
    resultats = [
        muter_fichier(rel, tests, maximum=a.max_par_fichier, verbeux=a.verbeux)
        for rel, tests in CIBLES
    ]
    v = verdict_global(resultats, plancher=a.plancher)
    v["duree_s"] = round(time.time() - t0, 1)

    print()
    print("=" * 92)
    print("  SCORE DE MUTATION : %.1f %%   (%d tues / %d valides ; %d invalides)"
          % (100 * v["score_mutation"], v["tues"], v["mutants_valides"], v["invalides"]))
    print("=" * 92)
    if v["survivants"]:
        print("\n🔴 LES LIGNES QUE PERSONNE NE GARDE (%d) :" % v["survivants"])
        for d in v["detail"]:
            for s in d["survivants"]:
                print("   %s  ligne %-5d %s" % (d["fichier"], s["ligne"], s["operateur"]))
        print("\n  Chacune est un BUG PLAUSIBLE que la suite laisserait passer EN SILENCE.")
    else:
        print("\n  Aucun survivant sur les cibles : ces chemins sont reellement gardes.")

    out = RACINE / "data" / "reports" / "mutation_score.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
