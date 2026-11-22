r"""H16 — refus prospectifs des copies perdantes (pré-enregistrée au §21 du journal, 22/11 ~21:55 heure de Paris).

Juge, sur les SEULS fills reçus après le gel, si refuser certaines copies améliore le PnL net TOTAL d'une
règle de base figée. Lecture seule : relit le journal et la bande de prix, ne touche ni à l'apprenant ni à
sa campagne, n'écrit au registre chaîné qu'avec `--enregistrer` et un verdict tranché.

    tools\python\python.exe tools\goal2_refus_prospectif.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for p in (RACINE / "src", RACINE / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from hl_observer.experimental import apprentissage_parallele as AP  # noqa: E402
from hl_observer.experimental import cycles_fantomes as CF  # noqa: E402

GEL_MS = 1_795_386_600_000                 # 2026-11-22T22:30:00Z : rien avant n'est jugé
BASE = {"frac_tvl": 0.002, "stop_bps": 40.0, "horizon_ms": 3_600_000.0, "notional_usd": 20.0}
FILTRES = {
    "F1_deja_absorbe": lambda c: (c.get("absorption_bps") is not None and c["absorption_bps"] >= 5.0),
    "F2_trop_tard": lambda c: (c.get("latence_ms") is not None and c["latence_ms"] > 60_000),
    "F3_petit_signal": lambda c: (c.get("notionnel_leader_usd") is not None and c["notionnel_leader_usd"] < 5_000.0),
}
FILTRES["F4_union"] = lambda c: any(f(c) for k, f in FILTRES.items() if k != "F4_union")
ALPHA = 0.05 / 4                           # Bonferroni sur les 4 filtres
JOURS_MIN, REFUS_MIN, COUVERTURE_MIN = 5, 50, 0.30


def cycles_de_base(root: Path, now_ms: float, *, lignes=None, tape=None, tvl=None) -> list[dict]:
    lignes = CF.lire_journal(root) if lignes is None else lignes
    tape = CF.bande_de_prix(root, depuis_ms=GEL_MS - 1_800_000) if tape is None else tape
    tvl = CF.tvl_par_vault(root) if tvl is None else tvl
    sim = CF.simuler(lignes, tape, tvl, frac_tvl=BASE["frac_tvl"], stop_bps=BASE["stop_bps"],
                     horizon_ms=BASE["horizon_ms"], depuis_ms=GEL_MS, now_ms=now_ms,
                     notional_usd=BASE["notional_usd"], etiquette="h16-base")
    return sim["cycles"]


def juger(cycles: list[dict]) -> dict:
    par_jour_base: dict[int, list[float]] = {}
    for c in cycles:
        par_jour_base.setdefault(int(c["entree_ms"] // AP.JOUR_MS), []).append(c["realized_usd"])
    jours = len(par_jour_base)
    sortie = {"cycles": len(cycles), "jours": jours, "base_total_usd": round(sum(c["realized_usd"] for c in cycles), 4),
              "contexte_absent": sum(1 for c in cycles if not c.get("contexte")), "filtres": {}}
    for nom, f in FILTRES.items():
        gardes, refuses = [], []
        gain_par_jour: dict[int, list[float]] = {j: [] for j in par_jour_base}
        garde_par_jour: dict[int, list[float]] = {j: [] for j in par_jour_base}
        for c in cycles:
            j = int(c["entree_ms"] // AP.JOUR_MS)
            if f(c.get("contexte") or {}):          # contexte absent : le filtre ne s'applique pas (copie gardée)
                refuses.append(c["realized_usd"])
                gain_par_jour[j].append(-c["realized_usd"])
            else:
                gardes.append(c["realized_usd"])
                garde_par_jour[j].append(c["realized_usd"])
                gain_par_jour[j].append(0.0)
        couverture = len(gardes) / len(cycles) if cycles else 0.0
        g = AP._bootstrap_jours(gain_par_jour, alpha=ALPHA)
        n = AP._bootstrap_jours(garde_par_jour, alpha=ALPHA)
        if jours < JOURS_MIN or len(refuses) < REFUS_MIN:
            statut = "MORE_DATA"
        elif couverture >= COUVERTURE_MIN and g[1] > 0 and n[1] > 0:
            statut = "PROMISING"
        else:
            statut = "REJECTED"
        sortie["filtres"][nom] = AP.sans_nan({
            "statut": statut, "gardes": len(gardes), "refuses": len(refuses), "couverture": round(couverture, 3),
            "filtre_total_usd": round(sum(gardes), 4), "pertes_evitees_usd": round(-sum(x for x in refuses if x < 0), 4),
            "profits_abandonnes_usd": round(sum(x for x in refuses if x > 0), 4),
            "gain_moyen_par_cycle_usd": [round(x, 5) for x in g], "garde_moyen_par_cycle_usd": [round(x, 5) for x in n]})
    return sortie


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--enregistrer", action="store_true", help="inscrit au registre chaîné si un verdict est tranché")
    a = p.parse_args(argv)
    now = time.time() * 1000
    if now < GEL_MS:
        print("  H16 : gel pas encore atteint, rien a juger")
        return 0
    r = juger(cycles_de_base(Path(a.racine), now))
    print(f"  H16 | depuis le gel : {r['cycles']} cycles resolus sur {r['jours']} jour(s) | base {r['base_total_usd']:+.2f} USD"
          f" | contexte absent {r['contexte_absent']}")
    for nom, x in r["filtres"].items():
        print(f"  {nom:<18} {x['statut']:<10} garde {x['gardes']:>5} refuse {x['refuses']:>5} (couverture {100 * x['couverture']:.0f} %)"
              f" | filtre {x['filtre_total_usd']:+.2f} USD | pertes evitees {x['pertes_evitees_usd']:.2f}"
              f" | profits abandonnes {x['profits_abandonnes_usd']:.2f}")
    if a.enregistrer and any(x["statut"] != "MORE_DATA" for x in r["filtres"].values()):
        import goal2_commun as G
        G.enregistrer({"hypothese": "H16_refus_prospectifs", "segment": "prospectif_apres_gel_22_11", "statut":
                       "PROMISING" if any(x["statut"] == "PROMISING" for x in r["filtres"].values()) else "REJECTED",
                       "parametres": {"gel_ms": GEL_MS, "base": BASE, "alpha": ALPHA}, "resultats": r})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
