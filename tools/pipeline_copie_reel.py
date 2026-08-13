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
import bisect
import json
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import functools  # noqa: E402

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.collection import vault_ledger as VL  # noqa: E402
from hl_observer.experimental.copy_edge_forward import (charger_prix_tape_candles, charger_prix_tape,  # noqa: E402
                                                        rendement_forward, rendement_forward_candles, geler)
from hl_observer.experimental.copy_edge_oos import (  # noqa: E402
    construire_table_prelim,
    mesurer_oos,
    simuler_paper,
)

FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
LEDGER = Path("runtime") / "data" / "vault_ledger.jsonl"
PRELIM = Path("runtime") / "data" / "copy_prelim_edge.json"
PRELIM_PROBE = Path("runtime") / "data" / "copy_prelim_probe.json"
HORIZONS_CANDLES_MS = (300_000.0, 900_000.0, 1_800_000.0, 3_600_000.0)   # 5/15/30/60 min (adaptés aux candles)
DELAI_COPIE_MS = 60_000.0        # délai de détection/copie appliqué avant l'entrée (anti-lookahead)

EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
SNAP = Path("runtime") / "data" / "vault_snapshots.jsonl"
RAPPORT = Path("runtime") / "data" / "copy_edge_rapport_reel.json"
MAX_NAV_AGE_MS = 6 * 3_600_000


def _legacy_latest_nav_par_vault(root: Path) -> dict[str, float]:
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


def _charger_entrees_alpha_legacy(root: Path) -> list[dict]:
    """Entrées alpha (OPEN/ADD hors retrait) depuis les épisodes backfillés, move_frac = taille/NAV."""
    try:
        episodes = [json.loads(l) for l in (root / EPISODES).read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return []
    nav = _legacy_latest_nav_par_vault(root)
    out = []
    for e in VB.entrees_alpha(episodes):
        n = nav.get(e.get("vault"), 0.0)
        if n > 0:
            out.append(dict(e, move_frac=round(float(e.get("taille_usd") or 0.0) / n, 4)))
    return out


def _charger_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        pass
    return rows


def _nav_history(root: Path) -> dict[str, list[tuple[int, float]]]:
    """Return sorted observable NAV history; future snapshots are never eligible."""
    history: dict[str, list[tuple[int, float]]] = {}
    for row in _charger_jsonl(root / SNAP):
        try:
            vault = str(row["vault"])
            ts_ms = int(row["ts_ms"])
            nav_usd = float(row["nav_usd"])
        except (KeyError, TypeError, ValueError):
            continue
        if vault and ts_ms > 0 and nav_usd > 0:
            history.setdefault(vault, []).append((ts_ms, nav_usd))
    for rows in history.values():
        rows.sort(key=lambda item: item[0])
    return history


def _nav_asof(
    history: dict[str, list[tuple[int, float]]], vault: str, ts_ms: int
) -> tuple[float, int] | None:
    rows = history.get(vault) or []
    index = bisect.bisect_right(rows, (int(ts_ms), float("inf"))) - 1
    if index < 0:
        return None
    nav_ts_ms, nav_usd = rows[index]
    if int(ts_ms) - nav_ts_ms > MAX_NAV_AGE_MS:
        return None
    return nav_usd, nav_ts_ms


def _fills_canoniques(root: Path) -> tuple[list[dict], dict[str, Any]]:
    """Merge backfill and causal WS increments without replaying snapshots."""

    historical = _charger_jsonl(root / FILLS)
    live_rows = _charger_jsonl(root / FILLS_LIVE)
    causal_live = [
        row for row in live_rows
        if row.get("source") == "LIVE_WS" and row.get("isSnapshot") is False
    ]
    # Put causal rows first.  ``dedupliquer`` is stable for equal event times,
    # so a fill seen both by WS and by a later REST backfill retains the only
    # provenance that can support a post-freeze forward claim.
    merged = causal_live + historical
    deduped = VB.dedupliquer(merged)
    return deduped, {
        "historical_fill_rows": len(historical),
        "live_fill_rows": len(live_rows),
        "causal_live_fill_rows": len(causal_live),
        "live_snapshot_rows_rejected": sum(
            1 for row in live_rows if row.get("isSnapshot") is True
        ),
        "live_unprovenanced_rows_rejected": sum(
            1 for row in live_rows if row.get("source") != "LIVE_WS"
        ),
        "merged_fill_rows": len(merged),
        "deduped_fill_rows": len(deduped),
        "cross_source_or_internal_duplicates_rejected": len(merged) - len(deduped),
        "causal_rows_preferred_on_duplicate": True,
        "live_policy": "LIVE_WS_AND_NOT_SNAPSHOT_ONLY",
    }


def _episodes_canoniques(root: Path) -> tuple[list[dict], dict[str, Any]]:
    fills, source_audit = _fills_canoniques(root)
    raw_fill_count = source_audit["merged_fill_rows"]
    if fills:
        episodes = VB.reconstruire_episodes(fills)
        VL.marquer_retraits_ledger(
            episodes,
            _charger_jsonl(root / LEDGER),
            heuristique_secours=VB.marquer_retraits,
        )
        source = "vault_fills_deduped_reconstructed"
    else:
        fills = []
        episodes = _charger_jsonl(root / EPISODES)
        source = "legacy_vault_episodes_fallback"

    seen: set[str] = set()
    canonical: list[dict] = []
    duplicate_episodes = 0
    for episode in sorted(episodes, key=lambda row: int(row.get("ts_ms") or 0)):
        event_id = str(episode.get("fill_id") or "")
        if not event_id:
            event_id = repr((
                episode.get("vault"), episode.get("ts_ms"), episode.get("coin"),
                episode.get("action"), episode.get("direction"), episode.get("taille_usd"),
                episode.get("px"), episode.get("oid") or episode.get("hash"),
            ))
        if event_id in seen:
            duplicate_episodes += 1
            continue
        seen.add(event_id)
        canonical.append(dict(episode, event_id=event_id))
    return canonical, {
        "episode_source": source,
        **source_audit,
        "raw_fills": raw_fill_count,
        "deduped_fills": len(fills),
        "duplicate_fills_rejected": source_audit["cross_source_or_internal_duplicates_rejected"],
        "raw_episodes": len(episodes),
        "canonical_episodes": len(canonical),
        "duplicate_episodes_rejected": duplicate_episodes,
    }


def charger_entrees_alpha_avec_audit(root: Path) -> tuple[list[dict], dict[str, Any]]:
    """Build canonical alpha entries using only NAV known at signal time."""
    episodes, audit = _episodes_canoniques(root)
    history = _nav_history(root)
    alpha = VB.entrees_alpha(episodes)
    out: list[dict] = []
    nav_ages: list[int] = []
    rejected = 0
    for episode in alpha:
        ts_ms = int(episode.get("ts_ms") or 0)
        nav = _nav_asof(history, str(episode.get("vault") or ""), ts_ms)
        if nav is None:
            rejected += 1
            continue
        nav_usd, nav_ts_ms = nav
        nav_age_ms = ts_ms - nav_ts_ms
        nav_ages.append(nav_age_ms)
        out.append(dict(
            episode,
            move_frac=round(float(episode.get("taille_usd") or 0.0) / nav_usd, 8),
            nav_at_signal_usd=nav_usd,
            nav_ts_ms=nav_ts_ms,
            nav_age_ms=nav_age_ms,
        ))
    audit.update({
        "nav_policy": "last_snapshot_at_or_before_signal",
        "max_nav_age_ms": MAX_NAV_AGE_MS,
        "alpha_before_nav_gate": len(alpha),
        "alpha_entries": len(out),
        "missing_or_stale_asof_nav_rejected": rejected,
        "nav_age_max_ms": max(nav_ages) if nav_ages else None,
        "nav_age_mean_ms": round(sum(nav_ages) / len(nav_ages), 3) if nav_ages else None,
    })
    return out, audit


def charger_entrees_alpha(root: Path) -> list[dict]:
    return charger_entrees_alpha_avec_audit(root)[0]


def _charger_fills(root: Path) -> list[dict]:
    return _fills_canoniques(root)[0]


def construire(
    root: Path,
    *,
    geler_si_valide: bool = True,
    on_parameters_selected: Callable[[dict[str, Any]], None] | None = None,
    cost_components_bps: Mapping[str, float] | None = None,
) -> dict:
    entrees, canonical_audit = charger_entrees_alpha_avec_audit(root)
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
    m = mesurer_oos(
        entrees,
        tape,
        on_parameters_selected=on_parameters_selected,
        **kw,
    )
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
           "canonical_input_audit": canonical_audit,
           "n_coins_prelim_positifs": len(table_prelim), "mesure": m}
    if m.get("statut") in ("PRELIMINAIRE", "VALIDATION"):
        variantes = list(m.get("grille_train") or [])
        rap["ranking_variantes_train"] = sorted(
            variantes, key=lambda row: float(row.get("train_net_bps") or float("-inf")), reverse=True
        )[:8]
        o = m["oos"]
        entrees_oos = [e for e in entrees if int(e.get("ts_ms") or 0) >= int(m["t_cut_ms"])]
        rap["simulation_paper_oos"] = simuler_paper(
            entrees_oos,
            tape,
            horizon_ms=o["horizon_ms"],
            seuil=o["seuil"],
            notional_usd=150.0,
            cout_ar_bps=m.get("frais_bps", 12.0),
            forward_fn=fwd,
            cost_components_bps=cost_components_bps,
        )
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
