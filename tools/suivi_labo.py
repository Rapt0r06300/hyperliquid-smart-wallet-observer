"""L'avancement du labo en deux phases, lu dans son journal, rafraichi en place.

Ne touche a RIEN : ouvre le journal en lecture, compte, affiche. Un ecran de suivi qui pourrait
perturber ce qu'il observe ne vaut pas la peine d'exister -- les collecteurs tournent a cote.

Ce qu'il montre, et pourquoi chaque ligne y est :

  * la PHASE en cours, parce que les deux n'ont pas la meme duree ni le meme sens : la phase 1
    prepare 33 tranches (lent, lineaire), la phase 2 explore des candidats (rapide, par lots) ;
  * le nombre d'essais et une estimation, calculee sur le DEBIT REEL observe depuis le premier
    essai -- pas sur une moyenne supposee ;
  * le STATUT et la RAISON tels que le labo les rend. Un `candidats essayes : 0` est affiche comme
    un REFUS, pas comme un resultat : c'est la distinction qui a manque pendant vingt-quatre
    heures ;
  * la RAM libre, parce que c'est elle qui decide si l'essai peut continuer sans gener la collecte.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]

#: Les journaux possibles, du plus specifique au plus general.
CANDIDATS = (
    RACINE / "runtime/reports/labo_phase2.log",
    RACINE / "runtime/reports/labo_chaine.log",
)

_ESSAI = re.compile(r"^\s*Essai\s+([\d\s,]+)")
_CLE = re.compile(r"^\s*(statut|raison|candidats essayes|economically_proven|daily_net_pnl_usd)\s*:\s*(.+)$")


def _journal(argv: list[str]) -> Path | None:
    """Le journal a suivre : celui donne en argument, sinon le plus recemment ecrit."""
    for arg in argv[1:]:
        chemin = Path(arg)
        if chemin.is_file():
            return chemin
    trouves = [p for p in CANDIDATS if p.is_file()]
    # Les journaux du bac a sable de la session, s'il y en a : on prend le plus frais.
    bac = Path(os.environ.get("TEMP", "")) / "claude"
    if bac.is_dir():
        trouves += sorted(bac.rglob("*chaine*.log"), key=lambda p: p.stat().st_mtime)[-1:]
        trouves += sorted(bac.rglob("phase2*.log"), key=lambda p: p.stat().st_mtime)[-1:]
    return max(trouves, key=lambda p: p.stat().st_mtime) if trouves else None


def _lire(chemin: Path) -> dict[str, Any]:
    essais: list[int] = []
    derniers: dict[str, str] = {}
    phase = "?"
    tranche = None
    with open(chemin, "rb") as flux:
        for brut in flux:
            ligne = brut.decode("utf-8", "replace").rstrip()
            if "PHASE 1" in ligne:
                phase = "1 — preparation des tranches"
            elif "PHASE 2" in ligne:
                phase = "2 — exploration des candidats"
            m = re.match(r"^\s*\[(\d+)/(\d+)\]", ligne)
            if m:
                tranche = (int(m.group(1)), int(m.group(2)))
            m = _ESSAI.match(ligne)
            if m:
                try:
                    essais.append(int(m.group(1).replace(" ", "").replace(",", "")))
                except ValueError:
                    pass
            m = _CLE.match(ligne)
            if m:
                derniers[m.group(1)] = m.group(2).strip()
    return {
        "phase": phase, "tranche": tranche, "essais": len(essais),
        "dernier_essai": essais[-1] if essais else None, "cles": derniers,
        "age_s": time.time() - chemin.stat().st_mtime,
    }


def _ram() -> tuple[float, float] | None:
    try:
        import psutil
    except ImportError:
        return None
    m = psutil.virtual_memory()
    return m.available / 1e9, m.total / 1e9


def rendre(etat: dict[str, Any], chemin: Path, debut: float, essais_au_debut: int) -> str:
    lignes = ["", "  ===== LABO EN DEUX PHASES =====", ""]
    lignes.append(f"  Phase      : {etat['phase']}")
    if etat["tranche"]:
        fait, total = etat["tranche"]
        barre = "#" * int(28 * fait / total) + "." * (28 - int(28 * fait / total))
        lignes.append(f"  Tranches   : [{barre}] {fait}/{total}")
    if etat["essais"]:
        ecoule = max(time.time() - debut, 1.0)
        faits = etat["essais"] - essais_au_debut
        debit = faits / ecoule * 60 if faits > 0 else 0.0
        lignes.append(f"  Essais     : {etat['essais']}" + (
            f"  ({debit:.0f}/min mesure)" if debit > 0 else ""))
    for cle, etiquette in (("statut", "Statut     "), ("raison", "Raison     "),
                           ("candidats essayes", "Candidats  "),
                           ("daily_net_pnl_usd", "PnL net/j  "),
                           ("economically_proven", "Prouve     ")):
        if cle in etat["cles"]:
            lignes.append(f"  {etiquette}: {etat['cles'][cle]}")
    if etat["cles"].get("candidats essayes") == "0":
        # LA distinction qui a manque pendant vingt-quatre heures.
        lignes.append("  >>> 0 candidat : ce n'est pas un PnL, c'est un REFUS (voir la raison)")
    ram = _ram()
    if ram:
        libre, total = ram
        alerte = "  [BAS]" if libre < 3.0 else ""
        lignes.append(f"  RAM libre  : {libre:.1f} / {total:.0f} Go{alerte}")
    frais = "en cours" if etat["age_s"] < 60 else f"silencieux depuis {etat['age_s']:.0f}s"
    lignes.append(f"  Journal    : {chemin.name} ({frais})")
    lignes.append("")
    lignes.append("  Ctrl+C pour fermer — cette fenetre ne touche a rien.")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    chemin = _journal(argv)
    if chemin is None:
        print("  Aucun journal du labo trouve.")
        print("  Lancez d'abord : tools/labo_deux_phases.py . --phase tout")
        print("  ou passez le chemin du journal en argument.")
        return 2
    debut = time.time()
    etat = _lire(chemin)
    essais_au_debut = etat["essais"]
    try:
        while True:
            etat = _lire(chemin)
            os.system("cls" if os.name == "nt" else "clear")
            print(rendre(etat, chemin, debut, essais_au_debut), flush=True)
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n  Suivi ferme. Le labo, lui, continue.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
