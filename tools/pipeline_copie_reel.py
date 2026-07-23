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

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.experimental.copy_edge_forward import charger_prix_tape_candles, charger_prix_tape, geler  # noqa: E402
from hl_observer.experimental.copy_edge_oos import mesurer_oos, simuler_paper, ranger_variantes, SEUILS_DEFAUT, HORIZONS_DEFAUT_MS  # noqa: E402

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


def construire(root: Path, *, intervalle: str = "1m", geler_si_valide: bool = True) -> dict:
    entrees = charger_entrees_alpha(root)
    tape = charger_prix_tape_candles(root, intervalle=intervalle)
    source = "candles"
    if not tape:                                                  # repli allMids (récent) si pas de candles
        tape, source = charger_prix_tape(root), "allmids"
    m = mesurer_oos(entrees, tape)
    rap = {"maj_ms": int(time.time() * 1000), "source_prix": source, "n_entrees_alpha": len(entrees),
           "n_coins_tape": len(tape), "mesure": m}
    if m.get("statut") in ("PRELIMINAIRE", "VALIDATION"):
        variantes = [{"seuil": s, "horizon_ms": h} for s in SEUILS_DEFAUT for h in HORIZONS_DEFAUT_MS]
        rap["ranking_variantes"] = ranger_variantes(entrees, tape, variantes=variantes)[:8]
        o = m["oos"]
        rap["simulation_paper_oos"] = simuler_paper(entrees, tape, horizon_ms=o["horizon_ms"], seuil=o["seuil"],
                                                    notional_usd=150.0, cout_ar_bps=m.get("frais_bps", 12.0))
        if geler_si_valide and m.get("edge_valide_oos"):
            rap["gel"] = geler(root, horizon_ms=o["horizon_ms"], edge_brut_bps=o["brut_bps"],
                               edge_net_mesure_bps=o["net_bps"], source="pipeline_reel_oos")
    return rap


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Orchestrateur pipeline réel de copie (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", default="1m")
    p.add_argument("--pas-de-gel", action="store_true")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    rap = construire(root, intervalle=a.intervalle, geler_si_valide=not a.pas_de_gel)
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
