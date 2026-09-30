"""VERDICT SUR LA DISPERSION CROSS-VENUE — les trois barres du protocole, appliquées telles quelles.

Protocole : `docs/audit/PROTOCOLE_CROSS_VENUE.md`, écrit AVANT la première donnée.
Les seuils sont recopiés ici en CONSTANTES : les changer se voit dans un diff, et un seuil qui
bouge après avoir vu le résultat n'est plus un seuil.

LES TROIS BARRES (une seule ratée = piste enterrée) :
  1. la dispersion doit amortir ses ~22 bps (4 jambes) en moins de 168 h ;
  2. elle doit rendre plus de 2 %/an — sinon elle est DOMINÉE par le carry mono-venue (0,82 %/an)
     tout en immobilisant du capital sur deux venues ;
  3. elle doit tenir : au-dessus du seuil plus de 60 % du temps, sur >= 72 h et >= 5 coins.

TROIS VERDICTS, JAMAIS DEUX : `EXPLOITABLE`, `REJETE`, `INSUFFISANT`. Le troisième n'est ni un
succès ni un échec — c'est l'absence de données, et la confondre avec un résultat est exactement
ce qui avait produit le faux « 1 sur 1M ».

Lecture seule. Aucun ordre, aucune promesse de PnL.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

# --- LES BARRES, recopiees du protocole. Toute modification doit se justifier dans un commit.
COUT_ALLER_RETOUR_BPS = 22.0        # 4 jambes : ouvrir + fermer sur 2 venues
COUT_ENTREE_BPS = 11.0
MAX_HEURES_AMORTISSEMENT = 168.0    # barre 1 : 7 jours
MIN_RENDEMENT_ANNUEL_PCT = 2.0      # barre 2 : ~2,4x le carry mono-venue (0,82 %/an)
MIN_PERSISTANCE = 0.60              # barre 3
MIN_HEURES_OBSERVEES = 72.0
MIN_COINS = 5
#: seuil de dispersion « utile » : ce qu'il faut par heure pour amortir l'entree en 168 h.
SEUIL_UTILE_BPS_H = COUT_ENTREE_BPS / MAX_HEURES_AMORTISSEMENT      # ~0,0655 bps/h

FICHIER = Path("runtime") / "data" / "dispersion_venues.jsonl"


def charger(root: Path) -> list[dict]:
    lignes = []
    try:
        with (root / FICHIER).open(encoding="utf-8", errors="ignore") as fh:
            for l in fh:
                l = l.strip()
                if not l:
                    continue
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if isinstance(r, dict) and isinstance(r.get("dispersion_bps_h"), (int, float)):
                    lignes.append(r)
    except OSError:
        return []
    return lignes


def juger(lignes: list[dict]) -> dict:
    if not lignes:
        return {"verdict": "INSUFFISANT", "motif": "aucune donnee collectee",
                "conseil": "lance le bot : le collecteur demarre tout seul."}

    ts = [float(r["ts"]) for r in lignes if isinstance(r.get("ts"), (int, float))]
    heures = (max(ts) - min(ts)) / 3600.0 if len(ts) > 1 else 0.0
    coins = {str(r.get("coin") or "") for r in lignes}
    disp = [float(r["dispersion_bps_h"]) for r in lignes]

    if heures < MIN_HEURES_OBSERVEES or len(coins) < MIN_COINS:
        return {"verdict": "INSUFFISANT",
                "motif": "%.1f h observees (min %.0f) · %d coins (min %d)"
                         % (heures, MIN_HEURES_OBSERVEES, len(coins), MIN_COINS),
                "n_observations": len(lignes),
                "conseil": "on ne conclut pas sur du vide : laisse tourner."}

    mediane = statistics.median(disp)
    persistance = sum(1 for d in disp if d >= SEUIL_UTILE_BPS_H) / len(disp)
    # rendement NET annualise : (dispersion captee sur l'annee) - (1 aller-retour)
    brut_an_bps = mediane * 24.0 * 365.0
    net_an_bps = brut_an_bps - COUT_ALLER_RETOUR_BPS
    rendement_pct = net_an_bps / 100.0
    heures_amorti = (COUT_ENTREE_BPS / mediane) if mediane > 0 else float("inf")

    barres = [
        ("1. amortir l'entree en < %.0f h" % MAX_HEURES_AMORTISSEMENT,
         heures_amorti <= MAX_HEURES_AMORTISSEMENT,
         "amortie en %.0f h" % heures_amorti if heures_amorti != float("inf") else "jamais"),
        ("2. rendre plus de %.1f %%/an" % MIN_RENDEMENT_ANNUEL_PCT,
         rendement_pct >= MIN_RENDEMENT_ANNUEL_PCT, "%.2f %%/an net" % rendement_pct),
        ("3. tenir > %.0f %% du temps" % (MIN_PERSISTANCE * 100),
         persistance >= MIN_PERSISTANCE, "%.0f %% du temps" % (persistance * 100)),
    ]
    ratees = [nom for nom, ok, _ in barres if not ok]
    return {
        "verdict": "EXPLOITABLE" if not ratees else "REJETE",
        "heures_observees": round(heures, 1), "coins": len(coins),
        "n_observations": len(lignes),
        "dispersion_mediane_bps_h": round(mediane, 5),
        "seuil_utile_bps_h": round(SEUIL_UTILE_BPS_H, 5),
        "rendement_net_annuel_pct": round(rendement_pct, 3),
        "heures_amortissement": None if heures_amorti == float("inf") else round(heures_amorti, 1),
        "persistance": round(persistance, 3),
        "barres": [{"barre": n, "passee": ok, "mesure": m} for n, ok, m in barres],
        "barres_ratees": ratees,
        "reference_carry_mono_venue_pct_an": 0.82,
        "promesse": "aucune — mesure descriptive sur donnees reelles",
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verdict cross-venue (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    a = p.parse_args(argv)
    rap = juger(charger(Path(a.root)))
    print(json.dumps(rap, ensure_ascii=False, indent=2))
    v = rap.get("verdict")
    if v == "INSUFFISANT":
        print("\n>>> INSUFFISANT — on ne conclut pas. " + str(rap.get("conseil", "")))
    elif v == "REJETE":
        print("\n>>> REJETE : %s." % ", ".join(rap.get("barres_ratees") or []))
        print("    On l'enterre comme le market making, le lead-lag et les autres. Les barres")
        print("    etaient fixees AVANT la donnee (docs/audit/PROTOCOLE_CROSS_VENUE.md) : on ne")
        print("    les deplace pas parce que le resultat deplait.")
    else:
        print("\n>>> EXPLOITABLE : les trois barres passent. Prochaine etape = paper via")
        print("    `funding/cross_venue_position` (deja ecrit et teste). Toujours 0 ordre reel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
