r"""H18 — refuser la copie qui ABSORBE une vague de liquidations (pré-enregistrée au §22 du journal).

Mêmes cycles que H16 (règle de base figée, données d'après le gel du 22/11 22:30 UTC). Refus F5 : ouverture
du leader dans l'heure d'une vague (définition H17) ou la suivante, dans le sens de l'absorbeur. Vagues tirées
du fichier Ironflow du mois : tant qu'il n'est pas publié, MORE_DATA. Lecture seule.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for p in (RACINE / "src", RACINE / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import goal2_absorption_liquidations as A  # noqa: E402
import goal2_refus_prospectif as R  # noqa: E402
from hl_observer.experimental import apprentissage_parallele as AP  # noqa: E402

REFUS_MIN = 20
ALPHA = 0.05


def marquer(cycles: list[dict], vg) -> list[dict]:
    """Ajoute `contre_vague` à chaque cycle (True si l'ouverture absorbe une vague connue)."""
    par_coin = {c: g for c, g in vg.groupby("coin")} if len(vg) else {}
    for c in cycles:
        g = par_coin.get(c.get("coin"))
        t = c.get("entree_ms") - ((c.get("contexte") or {}).get("latence_ms") or 0)     # instant du fill du leader
        c["contre_vague"] = bool(g is not None and any(
            h <= t < h + 2 * A.G.HEURE_MS and int(s) == int(c.get("sens"))
            for h, s in zip(g["heure_ms"], g["sens_absorbeur"])))
    return cycles


def juger(cycles: list[dict]) -> dict:
    par_jour: dict[int, list[float]] = {}
    gain: dict[int, list[float]] = {}
    garde: dict[int, list[float]] = {}
    refuses = []
    for c in cycles:
        j = int(c["entree_ms"] // AP.JOUR_MS)
        par_jour.setdefault(j, []).append(c["realized_usd"])
        gain.setdefault(j, [])
        garde.setdefault(j, [])
        if c["contre_vague"]:
            refuses.append(c["realized_usd"])
            gain[j].append(-c["realized_usd"])
        else:
            gain[j].append(0.0)
            garde[j].append(c["realized_usd"])
    couverture = 1 - len(refuses) / len(cycles) if cycles else 0.0
    g, n = AP._bootstrap_jours(gain, alpha=ALPHA), AP._bootstrap_jours(garde, alpha=ALPHA)
    if len(par_jour) < R.JOURS_MIN or len(refuses) < REFUS_MIN:
        statut = "MORE_DATA"
    elif couverture >= R.COUVERTURE_MIN and g[1] > 0 and n[1] > 0:
        statut = "PROMISING"
    else:
        statut = "REJECTED"
    return AP.sans_nan({"statut": statut, "cycles": len(cycles), "jours": len(par_jour), "refuses": len(refuses),
                        "couverture": round(couverture, 3), "gain": g, "garde": n})


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    now = time.time() * 1000
    try:
        vg = A.vagues(A.liquidations_horaires(R.GEL_MS, int(now)), R.GEL_MS, int(now))
    except FileNotFoundError as exc:
        print(f"  H18 : MORE_DATA — {exc}")
        return 0
    r = juger(marquer(R.cycles_de_base(RACINE, now), vg))
    print(f"  H18 : {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
