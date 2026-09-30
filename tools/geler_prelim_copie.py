"""GÈLE ET VERSIONNE la table d'edge préliminaire de copie (rectif Flo 23/07) — anti-réoptimisation.

Une fois les coins choisis, le forward ne doit JAMAIS les réoptimiser après coup. Cet outil copie la
table live (`copy_prelim_edge.json`) vers un fichier GELÉ VERSIONNÉ IMMUABLE (`copy_prelim_gele_v1.json`)
la PREMIÈRE fois seulement ; ensuite il refuse d'écraser (le gel est définitif). La cohorte exploratoire
lit en priorité ce fichier gelé. Pour re-figer après une VRAIE nouvelle mesure, incrémenter la version.

Lecture seule (copie un fichier local). Aucun ordre, aucune clé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
LIVE = Path("runtime") / "data" / "copy_prelim_edge.json"
GELE = Path("runtime") / "data" / "copy_prelim_gele_v1.json"


def geler(root: Path, *, forcer: bool = False) -> dict:
    dest = root / GELE
    if dest.exists() and not forcer:
        return {"statut": "DEJA_GELE", "fichier": str(GELE), "note": "gel définitif ; incrémenter la version pour re-figer"}
    try:
        live = json.loads((root / LIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"statut": "PAS_DE_TABLE_LIVE", "note": "lancer d'abord pipeline_copie_reel pour produire la table"}
    table = live.get("table") or {}
    payload = {"version": "v1", "gele_le_ms": int(time.time() * 1000), "source_prix": live.get("source_prix"),
               "n_coins": len(table), "coins": sorted(table),
               "note": "TABLE GELEE IMMUABLE — le forward ne se réoptimise jamais dessus. Chaque coin porte "
                       "son edge net préliminaire + le risque calibré (stop=MAE_p75, TP=MFE_p50).",
               "table": table}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"statut": "GELE", "fichier": str(GELE), "n_coins": len(table), "coins": sorted(table)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Gèle/version la table préliminaire de copie (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--forcer", action="store_true")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    r = geler(Path(a.root), forcer=a.forcer)
    print("[geler-prelim] %s" % json.dumps(r, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
