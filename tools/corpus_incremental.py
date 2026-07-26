"""INGESTION INCRÉMENTALE RÉELLE DU CORPUS (Flo 26/07, PT-2).

Architecture :
  - CYCLE 1 : catalogue COMPLET -> corpus historique IMMUABLE, indexé sur disque (historique/episodes.jsonl +
    manifest.json). C'est la seule fois où l'on parse tout.
  - CYCLES SUIVANTS : on NE recatalogue PAS. On lit le corpus historique depuis l'index (historical_context),
    on normalise UNIQUEMENT les new_events en NOUVEAUX SEGMENTS, et on ne rejoue que les affected_windows
    (coins réellement touchés) + les nouveaux segments.
Des COMPTEURS prouvent que le cycle 2 ne relit pas et ne rejoue pas les événements du cycle 1 :
`n_sources_parsees_ce_cycle`, `from_cache`, `n_hist_total`, `n_hist_rejoues`, `n_new_segments`. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
from pathlib import Path

HORIZONS_DEFAUT = (250, 1000, 5000, 30000)


def _dir(rundir: Path) -> Path:
    d = Path(rundir) / "historique"
    d.mkdir(parents=True, exist_ok=True)
    return d


def historique_present(rundir: Path) -> bool:
    return (_dir(rundir) / "manifest.json").exists()


def preparer_historique(root: Path, rundir: Path, *, cataloguer, construire) -> dict:
    """CYCLE 1 : parse tout, écrit l'index immuable + le source_manifest. CYCLES 2+ : recharge depuis le
    cache SANS recataloguer (from_cache=True, n_sources_parsees_ce_cycle=0)."""
    d = _dir(rundir)
    idx = d / "episodes.jsonl"
    man = d / "manifest.json"
    if man.exists() and idx.exists():
        manifest = json.loads(man.read_text(encoding="utf-8"))
        return {"corpus": _charger_episodes(idx), "manifest": manifest, "from_cache": True,
                "n_sources_parsees_ce_cycle": 0}
    cat = cataloguer(root, rundir)
    sources = cat.get("sources", [])
    cons = construire(sources, root=root)
    corpus = cons.get("episodes", [])
    with idx.open("w", encoding="utf-8") as f:                # index IMMUABLE (écrit une seule fois)
        for e in corpus:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    manifest = {"n_sources": len(sources), "n_episodes": len(corpus),
                "sources": [s.get("chemin") for s in sources[:200]],
                "accounting": cat.get("accounting", {}), "immuable": True}
    man.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "source_manifest.json").write_text(json.dumps({"sources": manifest["sources"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"corpus": corpus, "manifest": manifest, "from_cache": False,
            "n_sources_parsees_ce_cycle": len(sources)}


def _charger_episodes(idx: Path) -> list:
    out = []
    for l in Path(idx).read_text(encoding="utf-8", errors="ignore").splitlines():
        if l.strip():
            try:
                out.append(json.loads(l))
            except ValueError:
                continue
    return out


def segments_incrementaux(new_events, *, horizons=HORIZONS_DEFAUT) -> list:
    """Normalise UNIQUEMENT les new_events en épisodes-segments (les nouveaux). Un BBO brut (coin/bid/ask/ts)
    devient un épisode ; on ne fabrique aucun forward_mid (données réelles seulement) -> ces segments seront
    UNMEASURABLE tant que le forward n'est pas connu, ce qui est honnête."""
    segs = []
    for d in (new_events or []):
        bid, ask = d.get("bid"), d.get("ask")
        coin = d.get("coin") or d.get("symbol")
        if bid is None or ask is None or coin is None:
            continue
        segs.append({"coin": str(coin).upper(), "regime": d.get("regime", "live"),
                     "ts_ms": d.get("ts_wall_ms") or d.get("ts_ms") or d.get("exchange_ts") or 0,
                     "bid": float(bid), "ask": float(ask), "fwd_mid": d.get("fwd_mid") or {},
                     "_segment": "NEW"})
    return segs


def fenetre_active(corpus_hist, new_segments, affected_windows) -> dict:
    """Working set = sous-ensemble du corpus historique pour les COINS impactés + les nouveaux segments. On ne
    rejoue PAS tout l'historique. Rend {working, n_hist_total, n_hist_rejoues, n_new_segments, coins}."""
    coins = set((affected_windows or {}).get("coins") or [])
    for s in new_segments:
        coins.add(s["coin"])
    hist_actifs = [e for e in corpus_hist if not coins or e.get("coin") in coins]
    working = hist_actifs + list(new_segments)
    return {"working": working, "n_hist_total": len(corpus_hist), "n_hist_rejoues": len(hist_actifs),
            "n_new_segments": len(new_segments), "coins": sorted(coins)}


__all__ = ["historique_present", "preparer_historique", "segments_incrementaux", "fenetre_active", "HORIZONS_DEFAUT"]
