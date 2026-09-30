"""RECETTE WINDOWS — SMOKE BORNÉ, read-only, paper-only (Flo 26/07, FX-10).

Backbone AUTOMATISÉ de la recette Windows : lance N cycles (par défaut 2) du laboratoire continu sur les VRAIES
données déjà collectées (aucune donnée fabriquée ; si rien n'a été collecté, le run reste honnêtement pauvre),
FINALISE proprement SANS Ctrl+C (via max_cycles), puis RECALCULE les SHA du manifeste de CE run. Rend un code
0 si la finalisation est confirmée (rapport + manifeste + SHA recalculés concordants), 2 sinon.

À lancer PAR Flo sur Windows :  python tools\\recette_windows_smoke.py 2
SÉCURITÉ : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recherche_continue as RC  # noqa: E402


def main(cycles: int = 2) -> int:
    root = RC.RACINE
    r = RC.demarrer_foreground(root, exiger_flux=False, max_cycles=int(cycles),
                               collecteurs=None, afficher_live=False, mode="start")
    rid = RC._lire_dernier_run_lance(root)
    verif = RC.verifier_finalisation(root, rid) if rid else {"finalisation_confirmee": False, "raison": "PAS_DE_RUN"}
    sortie = {"run_id": rid, "finalisation": r.get("finalisation"), "start": r.get("start"),
              "verif_sha": verif, "securite": "0 ordre reel · 0 cle · 0 signature · 0 depot/retrait"}
    print(json.dumps(sortie, ensure_ascii=False, indent=1))
    return 0 if verif.get("finalisation_confirmee") else 2


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    raise SystemExit(main(n))
