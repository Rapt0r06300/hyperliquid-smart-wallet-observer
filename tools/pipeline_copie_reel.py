"""ORCHESTRATEUR DU PIPELINE RÉEL DE COPIE (rectif Flo 23/07) — la première VRAIE mesure locale.

Enchaîne sur les données DÉJÀ backfillées (par backfill_vault_fills : fills + ledger + épisodes, et
par backfill_candles : prix historiques) :
  épisodes → entrées ALPHA (retraits ledger exclus) → move_frac (via NAV) → tape de prix CANDLES
  (recherche historique, séparée du forward L2 <1 s) → mesure OOS PURGÉE par période ET par vault vs
  placebo + IC → simulation paper (ROI cumulé & par trade) → RANKING des variantes → décision SCALE/KILL.

Écrit runtime/data/copy_edge_rapport_reel.json. Gèle la config SI un edge est VALIDÉ en OOS (le signal
copy_vault ne consomme que ça). NEED_MORE_DATA honnête tant que l'historique manque. Lecture seule,
aucun ordre. À lancer APRÈS les backfills (réseau, chez Flo)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import functools  # noqa: E402

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.experimental.copy_edge_forward import (charger_prix_tape_candles, charger_prix_tape,  # noqa: E402
                                                        rendement_forward, rendement_forward_candles, geler)
from hl_observer.experimental.copy_edge_oos import (mesurer_oos, simuler_paper, ranger_variantes,  # noqa: E402
                                                    construire_table_prelim, SEUILS_DEFAUT)

FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
PRELIM = Path("runtime") / "data" / "copy_prelim_edge.json"
PRELIM_PROBE = Path("runtime") / "data" / "copy_prelim_probe.json"
HORIZONS_CANDLES_MS = (300_000.0, 900_000.0, 1_800_000.0, 3_600_000.0)   # 5/15/30/60 min (adaptés aux candles)
DELAI_COPIE_MS = 60_000.0        # délai de détection/copie appliqué avant l'entrée (anti-lookahead)

EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
SNAP = Path("runtime") / "data" / "vault_snapshots.jsonl"
RAPPORT = Path("runtime") / "data" / "copy_edge_rapport_reel.json"


def _nav_par_vault(root: Path) -> dict[str, float]:
    nav: dict[str, float] = {}
    try:
        for l in (root / SNAP).read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("vault") and float(d.get("nav_usd") or 0) > 0:
                nav[d["vault"]] = float(d["nav_usd"])
    except OSError:
        pass
    return nav


def charger_entrees_alpha(root: Path) -> list[dict]:
    """Entrées alpha (OPEN/ADD hors retrait) depuis les épisodes backfillés, move_frac = taille/NAV."""
    try:
        episodes = [json.loads(l) for l in (root / EPISODES).read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return []
    nav = _nav_par_vault(root)
    out = []
    for e in VB.entrees_alpha(episodes):
        n = nav.get(e.get("vault"), 0.0)
        if n > 0:
            out.append(dict(e, move_frac=round(float(e.get("taille_usd") or 0.0) / n, 4)))
    return out


def _charger_fills(root: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in (root / FILLS).read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return []


def construire(root: Path, *, geler_si_valide: bool = True) -> dict:
    entrees = charger_entrees_alpha(root)
    # RECHERCHE = candles 5m (couvre le train : 5000 bougies = 416 h) -> 1m -> repli allMids récent
    tape, source = charger_prix_tape_candles(root, intervalle="5m"), "candles_5m"
    if not tape:
        tape, source = charger_prix_tape_candles(root, intervalle="1m"), "candles_1m"
    if not tape:
        tape, source = charger_prix_tape(root), "allmids"
    est_candles = source.startswith("candles")
    # forward ANTI-LOOKAHEAD (entrée 1re bougie après signal+délai) pour candles ; tick pour allmids
    fwd = functools.partial(rendement_forward_candles, delai_ms=DELAI_COPIE_MS) if est_candles else rendement_forward
    horizons = HORIZONS_CANDLES_MS if est_candles else None
    # AUDIT couverture/troncature RÉEL (par vault/coin), part des coins mesurables
    audit = VB.auditer_couverture(_charger_fills(root), coins_tape=set(tape)) if entrees else {}
    kw = {"forward_fn": fwd}
    if horizons:
        kw["horizons_ms"] = horizons
    m = mesurer_oos(entrees, tape, **kw)
    # TABLE PRÉLIMINAIRE par coin (edge net POSITIF, descriptif + risque calibré).
    hz = (horizons or HORIZONS_CANDLES_MS)
    # ALPHA : avec KILL risque strict (risque ≫ edge exclu) — source du gate de la cohorte stricte.
    table_alpha = construire_table_prelim(entrees, tape, forward_fn=fwd, horizons_ms=hz, appliquer_kill_risque=True)
    (root / PRELIM).write_text(json.dumps({"maj_ms": int(time.time() * 1000), "source_prix": source,
                                           "n_coins_positifs": len(table_alpha), "table": table_alpha},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    # PROBE : édition LARGE (edge net>0 gardé même si risque élevé, mais stop/TP calibré) — pour OBSERVER
    # en tout petit les autres coins liquides sans polluer le PnL ALPHA.
    table_probe = construire_table_prelim(entrees, tape, forward_fn=fwd, horizons_ms=hz, appliquer_kill_risque=False)
    (root / PRELIM_PROBE).write_text(json.dumps({"maj_ms": int(time.time() * 1000), "source_prix": source,
                                                 "n_coins_positifs": len(table_probe), "table": table_probe},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    table_prelim = table_alpha
    rap = {"maj_ms": int(time.time() * 1000), "source_prix": source, "delai_copie_ms": DELAI_COPIE_MS,
           "n_entrees_alpha": len(entrees), "n_coins_tape": len(tape), "couverture": audit,
           "n_coins_prelim_positifs": len(table_prelim), "mesure": m}
    if m.get("statut") in ("PRELIMINAIRE", "VALIDATION"):
        variantes = [{"seuil": s, "horizon_ms": h} for s in SEUILS_DEFAUT for h in (horizons or HORIZONS_CANDLES_MS)]
        rap["ranking_variantes"] = ranger_variantes(entrees, tape, variantes=variantes, forward_fn=fwd)[:8]
        o = m["oos"]
        rap["simulation_paper_oos"] = simuler_paper(entrees, tape, horizon_ms=o["horizon_ms"], seuil=o["seuil"],
                                                    notional_usd=150.0, cout_ar_bps=m.get("frais_bps", 12.0), forward_fn=fwd)
        if geler_si_valide and m.get("edge_valide_oos"):
            rap["gel"] = geler(root, horizon_ms=o["horizon_ms"], edge_brut_bps=o["brut_bps"],
                               edge_net_mesure_bps=o["net_bps"], source="pipeline_reel_oos")
    return rap


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Orchestrateur pipeline réel de copie (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--pas-de-gel", action="store_true")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    rap = construire(root, geler_si_valide=not a.pas_de_gel)
    (root / RAPPORT).write_text(json.dumps(rap, ensure_ascii=False, indent=1), encoding="utf-8")
    m = rap["mesure"]
    print("[pipeline-reel] entrees_alpha=%d source_prix=%s statut=%s"
          % (rap["n_entrees_alpha"], rap["source_prix"], m.get("statut")), flush=True)
    if m.get("statut") in ("PRELIMINAIRE", "VALIDATION"):
        o = m["oos"]
        print("[pipeline-reel] OOS net=%.1fbps IC95=[%s,%s] placebo=%.1f -> DECISION=%s"
              % (o["net_bps"], o["ic95_bas_bps"], o["ic95_haut_bps"], o["placebo_bps"], m["decision"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
