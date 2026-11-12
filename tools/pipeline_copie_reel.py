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
from hl_observer.backtesting.copy_vault_causal_selection import causal_live_observation  # noqa: E402
from hl_observer.collection.forward_poll_fills import is_causal_live_source  # noqa: E402
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
                nav[VB.normaliser_vault(d["vault"])] = float(d["nav_usd"])
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
        n = nav.get(VB.normaliser_vault(e.get("vault")), 0.0)
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


def _strict_positive_timestamp_ms(value: object) -> int | None:
    """Parse a positive millisecond timestamp without truncating invalid input."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            parsed = int(raw)
            return parsed if parsed > 0 else None
    return None


def _nav_history(root: Path) -> dict[str, list[tuple[int, float]]]:
    """Return sorted observable NAV history keyed by canonical vault identity."""
    history: dict[str, list[tuple[int, float]]] = {}
    for row in _charger_jsonl(root / SNAP):
        try:
            vault = VB.normaliser_vault(row["vault"])
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
    rows = history.get(VB.normaliser_vault(vault)) or []
    index = bisect.bisect_right(rows, (int(ts_ms), float("inf"))) - 1
    if index < 0:
        return None
    nav_ts_ms, nav_usd = rows[index]
    if int(ts_ms) - nav_ts_ms > MAX_NAV_AGE_MS:
        return None
    return nav_usd, nav_ts_ms


#: Champs d'un fill live utiles à la déduplication et à la reconstruction des cycles. Le ruban
#: live matérialisé pèse plusieurs Go : on ne garde en mémoire que ces champs, ligne par ligne.
_CHAMPS_FILL_LIVE = (
    "vault", "ts_ms", "coin", "px", "sz", "signe", "dir", "start_position", "startPosition",
    "oid", "tid", "hash", "stable_event_id", "source", "isSnapshot", "is_snapshot",
    "received_at_ms", "side", "side_raw", "fill_side", "dir_raw", "start_position_raw",
    "crossed", "source_dataset_id", "source_shard_sha256", "source_raw_sha256",
    "provenance_tier",
)


def _iter_jsonl(path: Path):
    """Itère les objets d'un JSONL sans charger le fichier entier (rubans de plusieurs Go)."""
    try:
        handle = path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _fills_canoniques(root: Path) -> tuple[list[dict], dict[str, Any]]:
    """Merge backfill and causal live increments (WS or disciplined poll) without snapshots.

    La provenance causale suit le point unique de vérité ``is_causal_live_source`` : un fill
    ``LIVE_POLL`` (poll forward discipliné, horodaté à NOTRE réception) est causal au même titre
    qu'un fill ``LIVE_WS``. Son instant d'observation reste ``received_at_ms`` : il n'est jamais
    avancé à l'heure du fill.
    """

    historical = _charger_jsonl(root / FILLS)
    causal_live: list[dict] = []
    unclocked_live: list[dict] = []
    live_rows = live_incremental = snapshots = unprovenanced = 0
    causal_by_source: dict[str, int] = {}
    for row in _iter_jsonl(root / FILLS_LIVE):
        live_rows += 1
        source = row.get("source")
        if row.get("isSnapshot") is True:
            snapshots += 1
        if not is_causal_live_source(source):
            unprovenanced += 1
            continue
        if row.get("isSnapshot") is not False:
            continue
        live_incremental += 1
        try:
            event_ms = int(row.get("ts_ms") or 0)
            received_ms = int(row.get("received_at_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            event_ms = received_ms = 0
        slim = {key: row[key] for key in _CHAMPS_FILL_LIVE if key in row}
        if event_ms > 0 and received_ms >= event_ms:
            causal_live.append(slim)
            causal_by_source[str(source)] = causal_by_source.get(str(source), 0) + 1
        else:
            unclocked_live.append(slim)
    # Put causal rows first. ``dedupliquer`` applies the same hierarchy
    # independently of read order: causal live > REST/non-live > unclocked live.
    # Legacy unclocked live rows remain audit history but can never displace REST.
    merged = causal_live + historical + unclocked_live
    deduped = VB.dedupliquer(merged)
    return deduped, {
        "historical_fill_rows": len(historical),
        "live_fill_rows": live_rows,
        "live_incremental_rows": live_incremental,
        "causal_live_fill_rows": len(causal_live),
        "causal_live_fill_rows_by_source": dict(sorted(causal_by_source.items())),
        "live_incremental_without_valid_receive_time_audit_only": len(unclocked_live),
        "live_snapshot_rows_rejected": snapshots,
        "live_unprovenanced_rows_rejected": unprovenanced,
        "merged_fill_rows": len(merged),
        "deduped_fill_rows": len(deduped),
        "cross_source_or_internal_duplicates_rejected": len(merged) - len(deduped),
        "causal_rows_preferred_on_duplicate": True,
        "live_policy": "CAUSAL_LIVE_SOURCE_WS_OR_POLL_AND_NOT_SNAPSHOT_AND_VALID_LOCAL_RECEIVE_TIME",
    }


#: Dernière reconstruction des cycles, réutilisée tant que les fichiers d'entrée sont inchangés
#: (même chemin, même taille, même date de modification). Le labo appelait deux fois la
#: reconstruction (entrées puis cycles de vie) : sur un ruban de plusieurs Go, c'était relire et
#: reconstruire deux fois la même chose. Une seule entrée gardée, pour borner la mémoire.
_CYCLES_MEMORISES: dict[tuple, tuple[list[dict], dict[str, Any]]] = {}


def _signature_entrees(root: Path) -> tuple:
    signature: list[tuple[str, int, int]] = []
    for relatif in (FILLS, FILLS_LIVE, LEDGER, EPISODES):
        chemin = Path(root) / relatif
        try:
            etat = chemin.stat()
            signature.append((str(chemin.resolve()), etat.st_size, etat.st_mtime_ns))
        except OSError:
            signature.append((str(chemin), -1, -1))
    return tuple(signature)


def oublier_les_cycles() -> None:
    """Libère les épisodes mémorisés (3 millions de lignes sur le corpus réel du 2026-11-12, 2,3 Go) :
    à appeler quand plus aucune étape ne les relira dans ce processus."""
    _CYCLES_MEMORISES.clear()


def _episodes_canoniques(root: Path) -> tuple[list[dict], dict[str, Any]]:
    signature = _signature_entrees(root)
    memorise = _CYCLES_MEMORISES.get(signature)
    if memorise is not None:
        return list(memorise[0]), dict(memorise[1])
    episodes, audit = _reconstruire_episodes_canoniques(root)
    _CYCLES_MEMORISES.clear()
    _CYCLES_MEMORISES[signature] = (episodes, audit)
    return list(episodes), dict(audit)


def _reconstruire_episodes_canoniques(root: Path) -> tuple[list[dict], dict[str, Any]]:
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
    invalid_episode_timestamps = 0
    duplicate_episodes = 0
    timestamped_episodes: list[tuple[int, dict]] = []
    for episode in episodes:
        timestamp_ms = _strict_positive_timestamp_ms(episode.get("ts_ms"))
        if timestamp_ms is None:
            invalid_episode_timestamps += 1
            continue
        timestamped_episodes.append((timestamp_ms, episode))
    for timestamp_ms, episode in sorted(timestamped_episodes, key=lambda item: item[0]):
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
        canonical.append(dict(episode, event_id=event_id, ts_ms=timestamp_ms))
    return canonical, {
        "episode_source": source,
        **source_audit,
        "raw_fills": raw_fill_count,
        "deduped_fills": len(fills),
        "duplicate_fills_rejected": source_audit["cross_source_or_internal_duplicates_rejected"],
        "raw_episodes": len(episodes),
        "canonical_episodes": len(canonical),
        "duplicate_episodes_rejected": duplicate_episodes,
        "invalid_episode_timestamps_rejected": invalid_episode_timestamps,
    }


def charger_entrees_alpha_avec_audit(root: Path) -> tuple[list[dict], dict[str, Any]]:
    """Build canonical alpha entries using only NAV known at signal time."""
    episodes, audit = _episodes_canoniques(root)
    history = _nav_history(root)
    alpha = VB.entrees_alpha(episodes)
    out: list[dict] = []
    nav_ages: list[int] = []
    rejected = 0
    causal_nav_rejected = 0
    for episode in alpha:
        ts_ms = int(episode.get("ts_ms") or 0)
        nav = _nav_asof(history, str(episode.get("vault") or ""), ts_ms)
        if nav is None:
            rejected += 1
            if (
                causal_live_observation(episode)
                and int(episode.get("observed_at_ms") or 0) >= ts_ms > 0
            ):
                causal_nav_rejected += 1
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
        "causal_episodes": sum(
            1 for row in episodes
            if causal_live_observation(row)
            and int(row.get("observed_at_ms") or 0) >= int(row.get("ts_ms") or 0) > 0
        ),
        "causal_alpha_before_nav_gate": sum(
            1 for row in alpha
            if causal_live_observation(row)
            and int(row.get("observed_at_ms") or 0) >= int(row.get("ts_ms") or 0) > 0
        ),
        "causal_alpha_entries": sum(
            1 for row in out
            if causal_live_observation(row)
            and int(row.get("observed_at_ms") or 0) >= int(row.get("ts_ms") or 0) > 0
        ),
        "causal_missing_or_stale_asof_nav_rejected": causal_nav_rejected,
        "nav_age_max_ms": max(nav_ages) if nav_ages else None,
        "nav_age_mean_ms": round(sum(nav_ages) / len(nav_ages), 3) if nav_ages else None,
    })
    return out, audit


def charger_entrees_alpha_notional_fixe_avec_audit(
    root: Path,
) -> tuple[list[dict], dict[str, Any]]:
    """Charge les entrées causales sans inventer un NAV pour le sizing fixe.

    Le protocole historique reproduit un ratio de taille leader et exige donc
    un NAV as-of. La variante de continuation V4 utilise exclusivement le
    notional paper fixe du protocole exécutable : un NAV absent ne doit ni
    devenir zéro, ni supprimer une observation autrement causale.
    """

    episodes, audit = _episodes_canoniques(root)
    alpha = VB.entrees_alpha(episodes)
    out: list[dict[str, Any]] = []
    for episode in alpha:
        row = dict(episode)
        row.pop("move_frac", None)
        row.update(
            sizing_policy="FIXED_PAPER_NOTIONAL_USD",
            nav_required=False,
        )
        out.append(row)
    causal = [
        row
        for row in out
        if causal_live_observation(row)
        and int(row.get("observed_at_ms") or 0) >= int(row.get("ts_ms") or 0) > 0
    ]
    audit.update(
        {
            "nav_policy": "NOT_REQUIRED_FOR_FIXED_PAPER_NOTIONAL",
            "nav_required": False,
            "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            "usage_scope": "COPY_VAULT_V4_CAUSAL_CONTINUATION_ONLY",
            "alpha_before_nav_gate": len(alpha),
            "alpha_entries": len(out),
            "causal_alpha_entries": len(causal),
            "missing_or_stale_asof_nav_rejected": 0,
        }
    )
    return out, audit


def charger_evenements_lifecycle_avec_audit(
    root: Path,
) -> tuple[list[dict], dict[str, Any]]:
    """Expose les événements OPEN/ADD/REDUCE/CLOSE canoniques au replay paper."""

    return _episodes_canoniques(root)


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
