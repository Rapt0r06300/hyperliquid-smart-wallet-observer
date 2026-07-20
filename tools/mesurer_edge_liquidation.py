"""Runner #3/#530 — MESURE l'edge post-liquidation sur les donnees REELLES enregistrees.

Lit les liquidations (SQLite grappe_snapshots, ecrites par le moteur) + les marks de prix (replay
recorder), puis appelle mesurer_edge_liquidation. Imprime le VERDICT honnete
(EDGE_NET_POSITIF / PAS_D_EDGE / INSUFFISANT). Aucune donnee inventee : sans assez d'evenements,
le verdict est INSUFFISANT. MESURE only, aucun ordre.

  python tools/mesurer_edge_liquidation.py [--root .] [--horizon-s 1800] [--cout-bps 12]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.liquidation_edge_measure import (  # noqa: E402
    evenements_declenches, mesurer_edge_liquidation)
from hl_observer.market.liquidation_recorder import _db_path  # noqa: E402
from hl_observer.runtime.replay_recorder import read_replay_lines  # noqa: E402


def _lire_liquidations(root: str) -> list[dict]:
    path = _db_path(root)
    if not Path(path).exists():
        return []
    con = sqlite3.connect(str(path))
    try:
        cur = con.execute("SELECT coin, ts_ms, prix, sens FROM grappe_snapshots ORDER BY ts_ms")
        return [{"coin": c, "ts_ms": t, "prix": p, "sens": s} for (c, t, p, s) in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _lire_marks(root: str) -> dict[str, list]:
    base = Path(root) / "runtime" / "replay"
    out: dict[str, list] = {}
    for r in read_replay_lines(base, "marks.jsonl", include_archive=True):
        try:
            coin = str(r.get("coin") or "").upper()
            ts, mid = float(r.get("ts")), float(r.get("mid"))
        except (TypeError, ValueError):
            continue
        if coin and mid > 0:
            out.setdefault(coin, []).append((ts, mid))
    for c in out:
        out[c].sort()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mesure d'edge post-liquidation (read-only)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--horizon-s", type=float, default=1800.0)
    ap.add_argument("--cout-bps", type=float, default=12.0)
    a = ap.parse_args(argv)
    grappes = _lire_liquidations(a.root)
    marks = _lire_marks(a.root)
    # 🔴 20/07 : mesurer sur les SNAPSHOTS donnait +735 bps / hit 100 % / PF ∞ — un artefact
    # (entree au NIVEAU de la grappe, ~700 bps sous le marche, et la meme grappe comptee 54x).
    # On ne mesure QUE les grappes dont le niveau a ete FRANCHI par le mark (entree au mark).
    evs = evenements_declenches(grappes, marks)
    rap = mesurer_edge_liquidation(evs, marks, horizon_s=a.horizon_s, cout_aller_retour_bps=a.cout_bps)
    d = rap.as_dict()
    d["grappes_snapshots"] = len(grappes)
    d["evenements_declenches"] = len(evs)
    print(json.dumps(d, ensure_ascii=False, indent=2))
    if rap.verdict == "INSUFFISANT":
        _dire_quoi_faire(a.root, len(evs))
    return 0


def _dire_quoi_faire(root: str, n_evenements: int) -> None:
    """DIRE LE BON REMEDE — la version precedente conseillait TOUJOURS « laisse tourner plus
    longtemps ». Ce conseil a ete faux deux fois de suite :

      * le 19/07 au matin : RIEN n'ecrivait les liquidations (le recorder n'etait pas cable).
        On pouvait attendre un mois pour zero ligne.
      * le 19/07 l'apres-midi : le collecteur tournait ET lisait 692 positions reelles, mais les
        filtres de `construire_carte` les rejetaient toutes (4 seulement a moins de 10 % du prix,
        et jamais 2 wallets au meme niveau). Attendre n'y change RIEN : c'est la POPULATION
        observee -- le haut du leaderboard, peu leverage -- qui ne convient pas a la question.

    Un garde-fou qui indique le mauvais remede fait perdre des jours a quelqu'un qui croit bien
    faire. On lit donc l'etat REEL avant de conseiller quoi que ce soit.
    """
    from pathlib import Path
    log = Path(root) / "runtime" / "logs" / "liq-collector.log"
    texte = ""
    try:
        texte = log.read_text(encoding="utf-8", errors="ignore")[-4000:]
    except OSError:
        pass

    print("\n>>> INSUFFISANT — on ne conclut pas sur du vide. Mais AVANT d'attendre, "
          "voici POURQUOI c'est vide :\n")
    if not texte:
        print("    Le collecteur de liquidations n'a jamais tourne (aucun "
              "runtime/logs/liq-collector.log).")
        print("    -> Lance le bot : il le demarre tout seul. Verifie avec TESTER-COLLECTEURS.cmd.")
        return
    if "POURQUOI 0 GRAPPE" in texte:
        bloc = [l for l in texte.splitlines() if "[liq]" in l][-8:]
        print("    Le collecteur TOURNE et lit des positions reelles, mais les filtres les")
        print("    rejettent. Dernier diagnostic du collecteur :\n")
        for l in bloc:
            print("      " + l.strip())
        print("\n    -> ATTENDRE NE SERVIRA A RIEN : ce n'est pas un manque de temps, c'est une")
        print("       population inadaptee. Les gros comptes du leaderboard sont peu leverages ;")
        print("       leur prix de liquidation est trop loin du marche pour entrer dans le rayon")
        print("       de 10 %. Pour que cette piste vive, il faudrait viser des comptes a FORT")
        print("       LEVIER, ou enregistrer LARGE et filtrer au moment de la mesure.")
        print("       Aucune des deux n'est faite aujourd'hui -- c'est un choix a prendre, pas un bug.")
        return
    if n_evenements == 0:
        print("    Le collecteur tourne mais n'a encore rien ecrit. Regarde "
              "runtime/logs/liq-collector.log.")
    else:
        print("    %d evenement(s) enregistre(s) : c'est un vrai debut, mais sous le seuil de "
              "credibilite." % n_evenements)
        print("    -> LA, laisser tourner a du sens (voir docs/RUNBOOK_COLLECTE_DONNEES.md).")


if __name__ == "__main__":
    raise SystemExit(main())
