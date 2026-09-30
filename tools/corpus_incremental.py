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
import os
from pathlib import Path
import time

HORIZONS_DEFAUT = (250, 1000, 5000, 30000)


def _publier_progression(callback, *, courant: int, total: int | None, detail: str, unite: str) -> None:
    if callback is None:
        return
    try:
        callback(courant=courant, total=total, detail=detail, unite=unite)
    except TypeError:
        callback(courant, total, detail)


def _dir(rundir: Path) -> Path:
    d = Path(rundir) / "historique"
    d.mkdir(parents=True, exist_ok=True)
    return d


def historique_present(rundir: Path) -> bool:
    return (_dir(rundir) / "manifest.json").exists()


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _ecrire_json_atomique(path: Path, payload: dict | list) -> None:
    """Écrit sans partager un nom .tmp fixe entre plusieurs processus."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _ecrire_jsonl_atomique(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def _fusionner_accounting(previous: dict, current: dict) -> dict:
    cumulative_keys = (
        "n_batch_detected",
        "n_catalogued",
        "n_parsed",
        "n_unusable",
        "n_excluded",
        "n_pending",
        "errors",
        "octets",
        "events",
    )
    merged = dict(previous or {})
    for key in cumulative_keys:
        merged[key] = int(previous.get(key, 0) or 0) + int(current.get(key, 0) or 0)
    merged["n_total_detected"] = int(
        current.get("n_total_detected", previous.get("n_total_detected", 0)) or 0
    )
    processed = int(merged.get("n_batch_detected", 0) or 0)
    merged["completeness_ratio"] = (
        round(int(merged.get("n_parsed", 0) or 0) / processed, 4)
        if processed
        else 0.0
    )
    return merged


def preparer_historique(
    root: Path,
    rundir: Path,
    *,
    cataloguer,
    construire,
    progress_callback=None,
    stop_event=None,
) -> dict:
    """Construit l'historique par lots bornés, persistants et reprenables.

    Chaque source découverte reste dans un plan figé jusqu'à son traitement.
    Le travail ne se met jamais en pause, mais un cycle ne lit qu'une enveloppe
    bornée de sources et d'octets. Après le bootstrap, les cycles réutilisent un
    working set borné au lieu de recharger tout l'index en mémoire.
    """
    d = _dir(rundir)
    idx = d / "episodes.jsonl"
    man = d / "manifest.json"
    working_path = d / "working_set.jsonl"
    source_plan_path = d / "source_plan.json"
    manifest: dict = {}
    if man.exists():
        try:
            manifest = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}

    if manifest.get("bootstrap_complete") and idx.exists():
        source = working_path if working_path.exists() else idx
        corpus = _charger_episodes(
            source,
            total_attendu=manifest.get("working_set_episodes") or manifest.get("n_episodes"),
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
        return {
            "corpus": corpus,
            "manifest": manifest,
            "from_cache": True,
            "n_sources_parsees_ce_cycle": 0,
            "bootstrap_complete": True,
            "bootstrap_progress_pct": 100.0,
            "n_sources_deferred": 0,
        }

    max_sources = _env_int("HYPERSMART_18H_MAX_SOURCES_PER_BOOTSTRAP", 256)
    max_batch_bytes = (
        _env_int("HYPERSMART_18H_MAX_BOOTSTRAP_MEGABYTES", 512) * 1024 * 1024
    )
    source_offset = int(manifest.get("next_source_offset", 0) or 0)
    source_plan: list[str] | None = None
    if source_plan_path.exists():
        try:
            loaded_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
            if isinstance(loaded_plan, list):
                source_plan = [str(item) for item in loaded_plan]
        except (OSError, ValueError):
            source_plan = None

    try:
        cat = cataloguer(
            root,
            rundir,
            source_offset=source_offset,
            max_sources=max_sources,
            max_batch_bytes=max_batch_bytes,
            source_paths=source_plan,
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
    except TypeError:
        cat = cataloguer(root, rundir)
    if source_plan is None:
        source_plan = [str(item) for item in cat.get("source_plan", [])]
        _ecrire_json_atomique(source_plan_path, source_plan)

    sources = cat.get("sources", [])
    try:
        cons = construire(
            sources,
            root=root,
            max_par_source=None,
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
    except TypeError:
        cons = construire(sources, root=root)
    corpus = cons.get("episodes", [])

    if stop_event is not None and stop_event.is_set():
        # Ne pas avancer le curseur après une lecture partielle. Le lot sera
        # repris à l'identique au cycle suivant : aucune source n'est perdue.
        return {
            "corpus": [],
            "manifest": {**manifest, "interrompu": True, "bootstrap_complete": False},
            "from_cache": False,
            "n_sources_parsees_ce_cycle": 0,
            "bootstrap_complete": False,
            "bootstrap_progress_pct": manifest.get("bootstrap_progress_pct", 0.0),
            "n_sources_deferred": manifest.get("n_sources_deferred"),
        }

    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as stream:
        for episode in corpus:
            stream.write(json.dumps(episode, ensure_ascii=False) + "\n")
    # Un lot peut ne contenir que des fichiers sans épisode BBO exploitable.
    # Dans ce cas on conserve le dernier working set non vide : le bootstrap
    # continue au prochain cycle sans retomber sur un corpus vide ou artificiel.
    if corpus or not working_path.exists():
        _ecrire_jsonl_atomique(working_path, corpus)
    working_set = corpus
    if not working_set and working_path.exists():
        working_set = _charger_episodes(
            working_path,
            total_attendu=manifest.get("working_set_episodes"),
            progress_callback=progress_callback,
            stop_event=stop_event,
        )

    total_sources = int(
        cat.get("accounting", {}).get("n_total_detected", len(source_plan))
        or len(source_plan)
    )
    next_offset = int(
        cat.get("next_source_offset", source_offset + len(sources)) or 0
    )
    complete = bool(cat.get("bootstrap_complete", next_offset >= total_sources))
    cumulative_accounting = _fusionner_accounting(
        manifest.get("accounting", {}),
        cat.get("accounting", {}),
    )
    new_manifest = {
        "n_sources": total_sources,
        "n_sources_processed": next_offset,
        "n_sources_deferred": max(0, total_sources - next_offset),
        "next_source_offset": next_offset,
        "n_episodes": int(manifest.get("n_episodes", 0) or 0) + len(corpus),
        "working_set_episodes": len(working_set),
        "last_batch_sources": [s.get("chemin") for s in sources],
        "accounting": cumulative_accounting,
        "bootstrap_complete": complete,
        "bootstrap_progress_pct": (
            round(100.0 * next_offset / total_sources, 3)
            if total_sources
            else 100.0
        ),
        "immuable": complete,
        "interrompu": False,
    }
    _ecrire_json_atomique(man, new_manifest)
    _ecrire_json_atomique(
        d / "source_manifest.json",
        {
            "source_plan_path": str(source_plan_path),
            "n_sources": total_sources,
            "n_sources_processed": next_offset,
        },
    )
    return {
        "corpus": working_set,
        "manifest": new_manifest,
        "from_cache": False,
        "n_sources_parsees_ce_cycle": len(sources),
        "bootstrap_complete": complete,
        "bootstrap_progress_pct": new_manifest["bootstrap_progress_pct"],
        "n_sources_deferred": new_manifest["n_sources_deferred"],
    }


def _charger_episodes(
    idx: Path,
    *,
    total_attendu: int | None = None,
    progress_callback=None,
    stop_event=None,
) -> list:
    out = []
    dernier_affichage = 0.0
    with Path(idx).open("r", encoding="utf-8", errors="ignore") as flux:
        for numero, l in enumerate(flux, 1):
            if stop_event is not None and stop_event.is_set():
                break
            if l.strip():
                try:
                    out.append(json.loads(l))
                except ValueError:
                    continue
            maintenant = time.monotonic()
            if maintenant - dernier_affichage >= 0.5:
                _publier_progression(
                    progress_callback,
                    courant=numero,
                    total=total_attendu,
                    detail=f"chargement de l'index historique : {numero} ligne(s)",
                    unite="episodes",
                )
                dernier_affichage = maintenant
    _publier_progression(
        progress_callback,
        courant=len(out),
        total=total_attendu or len(out),
        detail=f"index historique chargé : {len(out)} épisodes valides",
        unite="episodes",
    )
    return out


def _filtrer_historique(corpus_hist, coins: set[str], *, progress_callback=None, stop_event=None) -> list:
    hist_actifs = []
    total = len(corpus_hist)
    dernier_affichage = 0.0
    for numero, episode in enumerate(corpus_hist, 1):
        if stop_event is not None and stop_event.is_set():
            break
        if not coins or episode.get("coin") in coins:
            hist_actifs.append(episode)
        maintenant = time.monotonic()
        if maintenant - dernier_affichage >= 0.5:
            _publier_progression(
                progress_callback,
                courant=numero,
                total=total,
                detail=(
                    f"sélection des fenêtres actives : {numero}/{total} épisodes, "
                    f"{len(hist_actifs)} retenus"
                ),
                unite="episodes",
            )
            dernier_affichage = maintenant
    return hist_actifs


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


def fenetre_active(
    corpus_hist,
    new_segments,
    affected_windows,
    *,
    progress_callback=None,
    stop_event=None,
) -> dict:
    """Working set = sous-ensemble du corpus historique pour les COINS impactés + les nouveaux segments. On ne
    rejoue PAS tout l'historique. Rend {working, n_hist_total, n_hist_rejoues, n_new_segments, coins}."""
    coins = set((affected_windows or {}).get("coins") or [])
    for s in new_segments:
        coins.add(s["coin"])
    hist_actifs = _filtrer_historique(
        corpus_hist,
        coins,
        progress_callback=progress_callback,
        stop_event=stop_event,
    )
    working = hist_actifs + list(new_segments)
    return {"working": working, "n_hist_total": len(corpus_hist), "n_hist_rejoues": len(hist_actifs),
            "n_new_segments": len(new_segments), "coins": sorted(coins)}


__all__ = ["historique_present", "preparer_historique", "segments_incrementaux", "fenetre_active", "HORIZONS_DEFAUT"]
