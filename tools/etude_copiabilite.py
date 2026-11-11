"""Étude de copiabilité Copy-Vault sur le coffre LOCAL certifié (PAPER / READ-ONLY, hors ligne).

Répond à : « que reste-t-il au copieur après observation et coûts ? » (voir
``hl_observer.backtesting.copy_vault_copiability``). Lit uniquement les shards du coffre LOCAL
dont le SHA-256 correspond à ``LOCAL_INDEX.json`` (sinon le shard est écarté et signalé).

Sorties :
* ``runtime/reports/copy_vault_quant_lab/copiabilite/<run>/resultat.json`` + ``RAPPORT.md`` ;
* ``.../copiabilite/EXPERIENCES.ndjson`` : registre chaîné (SHA du précédent) de toutes les
  expériences, résultats négatifs compris — jamais réécrit ;
* ``runtime/data/copy_vault_besoins_collecte.json`` : besoins transmis aux collecteurs.

Les résultats sont EXPLORATOIRES (tier LOCAL) : ni preuve économique, ni promotion de champion.
Aucun accès réseau, aucune collecte, aucun ordre.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import copy_vault_copiability as cop  # noqa: E402

PARSER_VERSION = "fills-v1"
REPORT_DIR = Path("runtime/reports/copy_vault_quant_lab/copiabilite")
NEEDS_PATH = Path("runtime/data/copy_vault_besoins_collecte.json")
CACHE_DIR = Path("runtime/research_lab/data/copiabilite_cache")  # sous « data/ » : ignoré par Git
CADENCE_BY_ARCHETYPE = {
    "DIRECTIONAL_SLOW": "PRIORITAIRE", "SWING": "STANDARD", "HFT": "ARCHIVE", "INSUFFICIENT": "DECOUVERTE",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def select_shards(
    root: Path, wanted: dict[str, str] | None = None
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Shards du coffre LOCAL utilisables : présents ET de SHA-256 identique à l'index.

    ``wanted`` : famille -> fragment de nom exigé (vide = tous les shards de la famille)."""

    index_path = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    wanted = wanted or {"fills_forward": "vault_fills", "allmids": "", "book_l2": "", "asset_ctx": "",
                        "bbo": "", "micro_bbo": ""}
    selected: dict[str, list[dict[str, Any]]] = {family: [] for family in wanted}
    excluded: list[dict[str, Any]] = []
    for entry in index.get("shards", []):
        family = entry.get("famille")
        if family not in wanted or wanted[family] not in str(entry.get("shard")):
            continue
        path = root / str(entry["shard"])
        if not path.is_file():
            excluded.append({"shard": entry["shard"], "reason": "fichier_absent"})
            continue
        actual = _sha256_file(path)
        if actual != entry.get("sha256"):
            excluded.append({"shard": entry["shard"], "reason": "sha256_different_de_l_index"})
            continue
        selected[family].append({"path": str(path), "sha256": actual, "shard": entry["shard"]})
    for family in selected:
        selected[family].sort(key=lambda item: item["shard"])
    return selected, excluded


def _parse_fills_shard(job: tuple[str, str, str]) -> tuple[str, int, dict[str, int]]:
    """Analyse un shard de fills (processus fils) ; résultat mis en cache par SHA du shard."""

    path, sha, cache_dir, lag = job
    suffix = "" if lag is None else f"-lag{int(lag)}"
    cache = Path(cache_dir) / f"{PARSER_VERSION}{suffix}-{sha}.pkl"
    meta = cache.with_suffix(".json")
    if cache.is_file() and meta.is_file():
        info = json.loads(meta.read_text(encoding="utf-8"))
        return str(cache), int(info["rows"]), dict(info["rejects"])
    rows: list[tuple[Any, ...]] = []
    rejects: dict[str, int] = {}
    interned: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            try:
                record, reason = cop.parse_fill_row(json.loads(line), assumed_lag_ms=lag)
            except ValueError:
                record, reason = None, "json_invalide"
            if record is None:
                rejects[str(reason)] = rejects.get(str(reason), 0) + 1
                continue
            rows.append(tuple(interned.setdefault(v, v) if isinstance(v, str) else v for v in record))
    frame = pd.DataFrame(rows, columns=list(cop.FILL_COLUMNS))
    for name in ("vault", "coin", "dir"):
        frame[name] = frame[name].astype("category")
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")
    frame.to_pickle(tmp)
    os.replace(tmp, cache)
    meta.write_text(json.dumps({"rows": len(frame), "rejects": rejects}), encoding="utf-8")
    return str(cache), len(frame), rejects


def load_fills(
    shards: list[dict[str, Any]], cache_dir: Path, workers: int, *, assumed_lag_ms: int | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Charge les fills des shards. ``assumed_lag_ms`` : uniquement pour l'étude rétrospective."""
    jobs = [(item["path"], item["sha256"], str(cache_dir), assumed_lag_ms) for item in shards]
    rejects: dict[str, int] = {}
    frames = []
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        for cache, _rows, shard_rejects in pool.map(_parse_fills_shard, jobs):
            frame = pd.read_pickle(cache)
            for name in ("vault", "coin", "dir"):
                frame[name] = frame[name].astype(str)
            frames.append(frame)
            for reason, count in shard_rejects.items():
                rejects[reason] = rejects.get(reason, 0) + count
    if not frames:
        return pd.DataFrame(columns=list(cop.FILL_COLUMNS)), rejects
    return pd.concat(frames, ignore_index=True), rejects


def load_mid_panel(shards: list[dict[str, Any]], stale_ms: int) -> cop.PricePanel:
    def snapshots():
        for item in shards:
            with gzip.open(item["path"], "rt", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    mids = row.get("mids")
                    if isinstance(mids, dict):
                        # '#...' (marchés de résultat) et '@...' (spot) sont hors périmètre perp
                        yield row.get("ts_ms"), {k: v for k, v in mids.items() if not k.startswith(("#", "@"))}

    return cop.build_mid_panel(snapshots(), stale_ms=stale_ms)


def load_half_spreads(shards: list[dict[str, Any]], *, sample_every: int = 5, min_obs: int = 50) -> dict[str, float]:
    """Demi-spread médian (bps) par coin depuis les hauts de carnet Hyperliquid observés.

    Sources acceptées (toutes portent ``bid`` / ``ask``) : carnets L2, cotations BBO, BBO dense
    de la microstructure. Les lignes d'une autre venue ou sans cotation sont ignorées."""

    observed: dict[str, list[float]] = {}
    for item in shards:
        with gzip.open(item["path"], "rt", encoding="utf-8") as handle:
            for i, line in enumerate(handle):
                if i % sample_every or '"bid"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("venue") not in (None, "HL"):
                    continue
                bid, ask = row.get("bid"), row.get("ask")
                if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and ask > bid > 0:
                    observed.setdefault(str(row.get("coin")), []).append((ask - bid) / (ask + bid) * 1e4)
    return {coin: float(np.median(v)) for coin, v in sorted(observed.items()) if len(v) >= min_obs}


def load_funding(shards: list[dict[str, Any]]):
    """``(coin, ts_ms, taux horaire)`` depuis le contexte d'actif certifié (flux ``asset_ctx``)."""

    for item in shards:
        with gzip.open(item["path"], "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("funding") is not None:
                    yield str(row.get("coin") or ""), row.get("ts_ms"), row.get("funding")


def spread_shards(shards: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [*shards.get("book_l2", []), *shards.get("bbo", []), *shards.get("micro_bbo", [])]


def donnees_consommees(shards: dict[str, list[dict[str, Any]]], roles: dict[str, str]) -> dict[str, Any]:
    """Traçabilité : quelles familles certifiées cette étude a réellement lues, et pour quoi faire."""
    return {famille: {"shards": len(shards.get(famille, [])), "role": role}
            for famille, role in roles.items() if shards.get(famille)}


def _git_head(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def experiment_identity(root: Path, shards: dict[str, list[dict[str, Any]]], config: cop.CopiabilityConfig, price: str) -> dict[str, Any]:
    material = [(family, item["sha256"]) for family in sorted(shards) for item in shards[family]]
    corpus = hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()
    sources = {
        "copy_vault_copiability.py": _sha256_file(Path(cop.__file__)),
        "etude_copiabilite.py": _sha256_file(Path(__file__)),
    }
    config_sha = hashlib.sha256(json.dumps(config.as_dict(), sort_keys=True).encode()).hexdigest()
    return {
        "code_head": _git_head(root),
        "source_sha256": sources,
        "corpus_sha256": corpus,
        "corpus_tier": "LOCAL",
        "corpus_shards": {family: len(items) for family, items in shards.items()},
        "config_sha256": config_sha,
        "price_source": price,
        "experiment_id": hashlib.sha256(
            json.dumps([sources, corpus, config_sha, price], sort_keys=True).encode()
        ).hexdigest()[:24],
    }


def append_ledger(path: Path, record: dict[str, Any]) -> str:
    """Ajoute une ligne au registre chaîné ; n'écrase ni ne réordonne jamais l'existant."""

    path.parent.mkdir(parents=True, exist_ok=True)
    previous = "0" * 64
    if path.is_file():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            previous = json.loads(lines[-1])["record_sha256"]
    body = {**record, "previous_record_sha256": previous}
    body["record_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n")
    return body["record_sha256"]


def verify_ledger(path: Path) -> dict[str, Any]:
    """Revérifie la chaîne : toute ligne modifiée ou retirée casse l'enchaînement."""

    if not path.is_file():
        return {"status": "EMPTY", "records": 0}
    previous = "0" * 64
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        claimed = record.pop("record_sha256", None)
        expected = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if claimed != expected or record.get("previous_record_sha256") != previous:
            return {"status": "BROKEN", "records": count, "broken_at": count + 1}
        previous = claimed
        count += 1
    return {"status": "VERIFIED", "records": count, "head": previous}


def collection_plan(report: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Besoins et classes de cadence pour les collecteurs (faits mesurés, aucune donnée future)."""

    members: dict[str, list[str]] = {}
    for address, representative in report["sybil_units"].items():
        members.setdefault(representative, []).append(address)
    leaders = [
        {
            "unit": row["unit"], "addresses": sorted(members.get(row["unit"], [row["unit"]])),
            "archetype": row["archetype"], "cadence": CADENCE_BY_ARCHETYPE[row["archetype"]],
            "turnover_per_exposure_per_day": row["turnover_per_exposure_per_day"],
            "mean_exposure_usd": row["mean_exposure_usd"],
        }
        for row in report["classification"]
    ]
    return {
        "schema_version": "hypersmart.copy_vault_collection_needs.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": identity["experiment_id"],
        "corpus_sha256": identity["corpus_sha256"],
        "evidence_tier": cop.EVIDENCE_TIER_LOCAL,
        "policy": (
            "Les classes orientent le BUDGET de collecte, jamais l'appartenance à l'univers : aucune "
            "adresse n'est retirée (pas de biais de survie). Une classe peut changer à chaque étude."
        ),
        "needs": report["collection_needs"],
        "leaders": leaders,
        "paper_read_only": True,
        "real_execution": False,
    }


def render_report(report: dict[str, Any], identity: dict[str, Any], rejects: dict[str, int], excluded: list[Any]) -> str:
    def num(value: Any, digits: int = 2) -> str:
        return "n/d" if value is None else f"{value:,.{digits}f}"

    lag, inputs, mirror = report["observation_lag"], report["inputs"], report["mirror_episodes"]
    lines = [
        "# Étude de copiabilité Copy-Vault", "",
        f"- Expérience `{identity['experiment_id']}` · HEAD `{identity['code_head']}` · corpus LOCAL `{identity['corpus_sha256'][:16]}`",
        f"- Statut des preuves : **{cop.EVIDENCE_TIER_LOCAL}** — exploratoire, aucune rentabilité prouvée.",
        f"- Entrées : {inputs['fills']:,} fills uniques · {inputs['leaders']} adresses = {inputs['units']} opérateurs · {inputs['coins']} coins · "
        f"prix `{inputs['price_provenance']}` sur {num(inputs['price_market_hours'], 1)} h.",
        f"- Retard d'observation : médiane {num(lag.get('median_s'), 0)} s · p95 {num(lag.get('p95_s'), 0)} s.",
        f"- Lignes écartées (comptées, jamais silencieuses) : {json.dumps(rejects, ensure_ascii=False, sort_keys=True)}",
    ]
    if excluded:
        lines.append(f"- Shards écartés pour intégrité : {len(excluded)}")
    lines += ["", "## Verdicts", ""]
    for verdict in report["verdicts"]:
        lines.append(f"- `{verdict['hypothesis']}` → **{verdict['status']}** — {verdict.get('reason')}")
    segments = (report["decay"].get("segments") or {})
    if segments:
        horizons = report["config"]["horizons_s"]
        lines += ["", "## Dérive du prix dans le sens du leader (bps, moyenne entre opérateurs)", "",
                  "| Segment | opérateurs | perdu avant observation | " + " | ".join(f"obs+{h}s" for h in horizons) + " |",
                  "|---|---|---|" + "---|" * len(horizons)]
        for name in ("TAKER_OPEN", "TAKER_CLOSE", "MAKER_OPEN", "MAKER_CLOSE"):
            seg = segments.get(name)
            if not seg:
                continue
            cells = [num(seg["metrics"][f"from_observation_{h}s"]["mean"]) for h in horizons]
            lines.append(f"| {name} | {seg['units']} | {num(seg['metrics']['pre_observation_bps']['mean'])} | " + " | ".join(cells) + " |")
    if mirror.get("status") == "MEASURED":
        copied = mirror["copied"]
        lines += ["", "## Copie miroir des épisodes", "",
                  f"- {mirror['episodes']:,} épisodes ; {num((mirror['closed_before_observation_share'] or 0) * 100, 1)} % des épisodes clos l'étaient déjà quand l'ouverture est devenue observable.",
                  f"- Copiés et mesurables : {copied['episodes']:,} · brut {num(copied['gross_bps'])} bps · coûts {num(copied['cost_bps'])} bps · **net {num(copied['net_bps'])} bps** · réussite {num((copied['hit_rate'] or 0) * 100, 1)} %.",
                  f"- Statuts : {json.dumps(mirror['status_counts'], ensure_ascii=False)}"]
    universe = report["universe_attribution"]
    if universe:
        lines += ["", "## D'où vient le PnL des leaders (USD, fenêtre mesurée)", "",
                  f"- Exécution (capture de spread, non copiable) : {num(universe['execution_usd'], 0)}",
                  f"- Inventaire, information parfaite : {num(universe['inventory_true_usd'], 0)}"]
        for k in report["config"]["rebalance_minutes"]:
            lines.append(
                f"- Réplication causale, rééquilibrage {k} min : inventaire {num(universe[f'inventory_k{k}_usd'], 0)} · "
                f"coût {num(universe[f'cost_k{k}_usd'], 0)} · net {num(universe[f'net_k{k}_usd'], 0)}"
            )
        k_max = max(report["config"]["rebalance_minutes"])
        lines.append(f"- Funding de la position répliquée ({k_max} min) : {num(universe.get(f'funding_k{k_max}_usd'), 0)} USD ; "
                     f"taux inconnu sur {num(universe.get(f'funding_unmeasured_k{k_max}_usd_hours'), 0)} USD·heures (non compté).")
        lines.append("- Une fenêtre courte mesure surtout l'exposition au marché : ces montants ne sont pas un rendement attendu.")
    counts: dict[str, int] = {}
    for row in report["classification"]:
        counts[row["archetype"]] = counts.get(row["archetype"], 0) + 1
    lines += ["", "## Opérateurs par archétype", "", f"- {json.dumps(counts, ensure_ascii=False, sort_keys=True)}",
              "", "## Besoins transmis aux collecteurs", ""]
    for need in report["collection_needs"]:
        lines.append(f"- **{need['need']}** — {need['impact']} → {need['action']}")
    lines += ["", "PAPER / READ-ONLY : aucune collecte réseau, aucun ordre. Les verdicts TRAIN/LOCAL ne promeuvent aucun champion.", ""]
    return "\n".join(lines)


def run(root: Path, *, price: str, workers: int, config: cop.CopiabilityConfig, write: bool = True) -> dict[str, Any]:
    started = time.time()
    shards, excluded = select_shards(root)
    identity = experiment_identity(root, shards, config, price)
    print(f"[copiabilite] shards vérifiés : {identity['corpus_shards']} · écartés : {len(excluded)}", flush=True)
    raw, rejects = load_fills(shards["fills_forward"], root / CACHE_DIR, workers)
    print(f"[copiabilite] {len(raw):,} lignes de fills lues en {time.time() - started:.0f} s", flush=True)
    half_spreads = load_half_spreads(spread_shards(shards))
    aliases: dict[str, str] = {}
    if price == "mids":
        panel = load_mid_panel(shards["allmids"], config.stale_price_ms)
        panel, aliases = cop.alias_legacy_symbols(panel, raw["coin"].unique())
        if len(panel.ts):
            raw = raw[(raw["time"] >= int(panel.ts[0])) & (raw["time"] <= int(panel.ts[-1]))]
        fills, prepared_rejects = cop.prepare_fills(raw, config)
    else:
        fills, prepared_rejects = cop.prepare_fills(raw, config)
        panel = cop.build_print_panel(fills)
    del raw
    for reason, count in prepared_rejects.items():
        rejects[reason] = rejects.get(reason, 0) + count
    print(f"[copiabilite] {len(fills):,} fills retenus · panel {panel.px.shape} · {len(half_spreads)} demi-spreads", flush=True)
    funding = cop.build_funding_rates(load_funding(shards["asset_ctx"]), panel)
    report = _jsonable(cop.run_copiability_study(fills, panel, half_spreads, config, funding_rates=funding))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    result = {
        "run_id": run_id, "identity": identity, "rejects": dict(sorted(rejects.items())),
        "integrity_excluded_shards": excluded, "elapsed_seconds": round(time.time() - started, 1),
        "price_symbol_aliases": aliases,
        "donnees_consommees": donnees_consommees(shards, {
            "fills_forward": "fills des leaders (relevés REST et WebSocket) : signal étudié",
            "allmids": "prix de référence observés",
            "book_l2": "coût de spread", "bbo": "coût de spread (cotations)", "micro_bbo": "coût de spread (BBO dense)",
            "asset_ctx": "funding de la position répliquée"}),
        "evidence_tier": cop.EVIDENCE_TIER_LOCAL, "report": report,
    }
    if write:
        out_dir = root / REPORT_DIR / run_id
        _atomic_write_json(out_dir / "resultat.json", result)
        (out_dir / "RAPPORT.md").write_text(render_report(report, identity, result["rejects"], excluded), encoding="utf-8")
        ledger = {
            "run_id": run_id, **identity, "evidence_tier": cop.EVIDENCE_TIER_LOCAL,
            "hypotheses_tested": report["hypotheses_tested"],
            "verdicts": [{"hypothesis": v["hypothesis"], "status": v["status"], "reason": v.get("reason")} for v in report["verdicts"]],
            "config": report["config"], "inputs": {k: v for k, v in report["inputs"].items() if k != "sybil_clusters"},
            "result_path": str((REPORT_DIR / run_id / "resultat.json").as_posix()),
            "paper_read_only": True, "real_execution": False, "economically_proven": False,
        }
        result["ledger_record_sha256"] = append_ledger(root / REPORT_DIR / "EXPERIENCES.ndjson", ledger)
        _atomic_write_json(root / NEEDS_PATH, collection_plan(report, identity))
        print(f"[copiabilite] rapport : {out_dir / 'RAPPORT.md'}", flush=True)
    return result


CANDLES_PATH = Path("runtime/history/candles_5m.jsonl")
CANDLE_INTERVAL_MS = 300_000
EVIDENCE_TIER_RETROSPECTIVE = "LOCAL_RETROSPECTIVE_RECONSTRUCTED"


def bougies(root: Path, shards: dict[str, list[dict[str, Any]]]):
    """Bougies 5 min : celles du coffre (certifiées) si elles y sont, sinon le fichier brut — signalé.

    Renvoie ``(itérable, provenance)`` ; ``(None, ...)`` si aucune source n'existe."""
    certifiees = shards.get("candle") or []
    if certifiees:
        def lire():
            for item in certifiees:
                with gzip.open(item["path"], "rt", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and row.get("interval") == "5m":
                            yield str(row.get("coin") or ""), row.get("open_ts_ms"), row.get("close")
        empreinte = hashlib.sha256("".join(sorted(i["sha256"] for i in certifiees)).encode()).hexdigest()
        return lire(), {"origine": "COFFRE_CERTIFIE", "shards": len(certifiees), "sha256": empreinte}
    chemin = root / CANDLES_PATH
    if not chemin.is_file():
        return None, {"origine": "ABSENT", "sha256": None}
    return load_candles(chemin), {"origine": "FICHIER_BRUT_NON_CERTIFIE", "chemin": CANDLES_PATH.as_posix(),
                                  "sha256": _sha256_file(chemin)}


def load_candles(path: Path):
    """Bougies ``(coin, ouverture_ms, clôture)`` ; toute ligne illisible est ignorée (jamais devinée)."""

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield str(row.get("coin") or ""), row.get("t_ms"), row.get("c")


def render_retrospective_report(report: dict[str, Any], identity: dict[str, Any], rejects: dict[str, int],
                                *, titre: str | None = None, statut: str | None = None,
                                entrees: str | None = None) -> str:
    def num(value: Any, digits: int = 2) -> str:
        return "n/d" if value is None else f"{value:,.{digits}f}"

    inputs, scale = report["inputs"], report["economic_scale"]
    k = max(report["config"]["rebalance_minutes"])
    if entrees is None:
        entrees = (f"{inputs['fills']:,} fills de backfill · {inputs['leaders']} vaults · {inputs['coins']} coins · "
                   f"prix `{inputs['price_provenance']}` sur {num(inputs['price_market_hours'], 0)} h · "
                   f"retard d'observation SUPPOSÉ {report['assumed_observation_lag_ms'] / 1000:.0f} s.")
    lines = [
        titre or "# Réplication lente d'inventaire — étude RÉTROSPECTIVE", "",
        f"- Expérience `{identity['experiment_id']}` · HEAD `{identity['code_head']}` · corpus `{identity['corpus_sha256'][:16]}`",
        statut or f"- Statut des preuves : **{EVIDENCE_TIER_RETROSPECTIVE}** — historique reconstruit, jamais une preuve.",
        f"- Entrées : {entrees}",
        f"- Lignes écartées : {json.dumps(rejects, ensure_ascii=False, sort_keys=True)}",
        "", "## Limites à garder en tête", "",
    ]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    universe = report["universe_attribution"]
    if universe:
        lines += ["", f"## PnL d'inventaire répliqué, rééquilibrage {k} min (USD, somme des vaults)", "",
                  f"- Inventaire : {num(universe[f'inventory_k{k}_usd'], 0)} = part statique (pari directionnel moyen) "
                  f"{num(universe[f'static_k{k}_usd'], 0)} + part timing {num(universe[f'timing_k{k}_usd'], 0)}",
                  f"- Coût de rotation : {num(universe[f'cost_k{k}_usd'], 0)} · rotation non chiffrable (spread inconnu) : "
                  f"{num(universe[f'unmeasured_turnover_k{k}_usd'], 0)} USD",
                  f"- Funding de la position répliquée : {num(universe.get(f'funding_k{k}_usd'), 0)} USD "
                  f"(taux inconnu sur {num(universe.get(f'funding_unmeasured_k{k}_usd_hours'), 0)} USD·heures d'exposition : "
                  "non compté, jamais supposé nul)",
                  f"- **Net : {num(universe[f'net_k{k}_usd'], 0)}**"]
    for title, key in (("net (inventaire - coûts)", "persistence_net"), ("timing seul (net - part statique)", "persistence_timing")):
        p = report[key]
        stat = p.get("unit_daily_return_bps") or {}
        lines += ["", f"## Persistance — {title}", "",
                  f"- Verdict : **{p.get('status')}** — {p.get('reason')}",
                  f"- {p.get('eligible_units')} vault(s) éligible(s) · {p.get('usable_days')} jour(s) exploitable(s) · "
                  f"{p.get('walk_forward_days')} jour(s) en marche avant",
                  f"- Rendement journalier moyen par vault : {num(stat.get('mean'))} bps (médiane {num(stat.get('median'))}, "
                  f"IC 95 % {stat.get('ci95')}, {num((stat.get('share_positive') or 0) * 100, 0)} % de vaults positifs)",
                  f"- Marche avant (sélection sur le passé, mesure le jour suivant) : {num(p.get('walk_forward_mean_bps_per_day'))} bps/jour"
                  + (f", t = {num(p.get('walk_forward_t'))}" if p.get("walk_forward_t") is not None else ""),
                  f"- Corrélation de rang 1re moitié / 2e moitié : {num(p.get('split_half_rank_correlation'))}"]
    for title, key in (("net", "unit_tests_net"), ("timing seul", "unit_tests_timing")):
        tests = report[key]
        lines += ["", f"## Test par vault — {title}", "",
                  f"- {tests.get('units_tested', 0)} vault(s) testé(s) (≥ {tests.get('min_days')} jours) · "
                  f"{tests.get('units_positive_mean', 0)} à moyenne positive · "
                  f"**{tests.get('units_significant_after_bonferroni', 0)} significatif(s) après Bonferroni**"]
        if tests.get("units"):
            lines += ["", "| Vault | jours | bps/jour | t | seuil Bonferroni | jours positifs |", "|---|---|---|---|---|---|"]
            for row in tests["units"][:12]:
                lines.append(f"| `{row['unit'][:12]}…` | {row['days']} | {num(row['mean_bps_per_day'])} | {num(row['t'])} | "
                             f"{num(row['critical_t_bonferroni'])} | {num(row['share_positive_days'] * 100, 0)} % |")
    lines += ["", "## Ordre de grandeur pour notre capital", "",
              f"- Capital {num(scale['capital_usd'], 0)} USD sans levier : 10 bps/jour d'exposition = {num(scale['usd_per_day_per_10_bps'])} USD/jour.",
              f"- Au rendement moyen mesuré ci-dessus : {num(scale['implied_usd_per_day_at_mean'])} USD/jour (constat rétrospectif, pas une prévision).",
              "", "PAPER / READ-ONLY : aucune collecte réseau, aucun ordre. Un résultat rétrospectif ne promeut aucun champion.", ""]
    return "\n".join(lines)


def run_retrospective(root: Path, *, lag_s: float, workers: int, write: bool = True) -> dict[str, Any]:
    """Persistance de la réplication lente sur fills de backfill + bougies (historique reconstruit)."""

    started = time.time()
    lag_ms = int(lag_s * 1000)
    config = cop.CopiabilityConfig(rebalance_minutes=(60, 240))
    shards, excluded = select_shards(root, {"fills_backfill": "", "book_l2": "", "bbo": "", "micro_bbo": "",
                                            "asset_ctx": "", "candle": "candles_5m"})
    identity = experiment_identity(root, shards, config, f"candles_5m|lag={lag_ms}")
    candles, identity["candles_source"] = bougies(root, shards)
    if candles is None:
        return {"status": "UNMEASURABLE", "reason": f"bougies absentes : {CANDLES_PATH.as_posix()}", "identity": identity}
    identity["candles_sha256"] = identity["candles_source"]["sha256"]
    identity["corpus_tier"] = EVIDENCE_TIER_RETROSPECTIVE
    identity["experiment_id"] = hashlib.sha256(
        (identity["experiment_id"] + identity["candles_sha256"]).encode()
    ).hexdigest()[:24]
    raw, rejects = load_fills(shards["fills_backfill"], root / CACHE_DIR, workers, assumed_lag_ms=lag_ms)
    panel = cop.build_candle_panel(candles, interval_ms=CANDLE_INTERVAL_MS)
    if len(panel.ts):
        raw = raw[(raw["time"] >= int(panel.ts[0]) - CANDLE_INTERVAL_MS) & (raw["time"] <= int(panel.ts[-1]))]
    fills, prepared_rejects = cop.prepare_fills(raw, config)
    for reason, count in prepared_rejects.items():
        rejects[reason] = rejects.get(reason, 0) + count
    half_spreads = load_half_spreads(spread_shards(shards))
    funding = cop.build_funding_rates(load_funding(shards["asset_ctx"]), panel)
    print(f"[retrospectif] {len(fills):,} fills · {fills['vault'].nunique() if len(fills) else 0} vaults · "
          f"panel {panel.px.shape} · {len(half_spreads)} demi-spreads", flush=True)
    report = _jsonable(cop.run_retrospective_study(fills, panel, half_spreads, config, assumed_lag_ms=lag_ms,
                                                   funding_rates=funding))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-retro"
    result = {
        "run_id": run_id, "identity": identity, "rejects": dict(sorted(rejects.items())),
        "integrity_excluded_shards": excluded, "elapsed_seconds": round(time.time() - started, 1),
        "evidence_tier": EVIDENCE_TIER_RETROSPECTIVE, "report": report,
    }
    if write:
        out_dir = root / REPORT_DIR / run_id
        _atomic_write_json(out_dir / "resultat.json", result)
        (out_dir / "RAPPORT.md").write_text(render_retrospective_report(report, identity, result["rejects"]), encoding="utf-8")
        ledger = {
            "run_id": run_id, **identity, "evidence_tier": EVIDENCE_TIER_RETROSPECTIVE,
            "hypotheses_tested": report["hypotheses_tested"],
            "verdicts": [{"hypothesis": v["hypothesis"], "status": v["status"], "reason": v.get("reason")} for v in report["verdicts"]],
            "config": report["config"], "inputs": report["inputs"],
            "assumed_observation_lag_ms": lag_ms, "caveats": report["caveats"],
            "result_path": str((REPORT_DIR / run_id / "resultat.json").as_posix()),
            "paper_read_only": True, "real_execution": False, "economically_proven": False,
        }
        result["ledger_record_sha256"] = append_ledger(root / REPORT_DIR / "EXPERIENCES.ndjson", ledger)
        print(f"[retrospectif] rapport : {out_dir / 'RAPPORT.md'}", flush=True)
    return result


EVIDENCE_TIER_POSITIONS = "LOCAL_OBSERVED_POSITIONS_EXPLORATORY"


def load_snapshots(shards: list[dict[str, Any]]):
    """Instantanés de portefeuille certifiés (famille ``snapshot`` du coffre LOCAL)."""

    for item in shards:
        with gzip.open(item["path"], "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row


def run_positions(root: Path, *, price: str, write: bool = True) -> dict[str, Any]:
    """Réplication lente des PORTEFEUILLES OBSERVÉS des vaults (instantanés certifiés du coffre)."""

    started = time.time()
    config = cop.CopiabilityConfig(rebalance_minutes=(60, 240))
    shards, excluded = select_shards(root, {"snapshot": "", "book_l2": "", "allmids": "", "bbo": "",
                                            "micro_bbo": "", "asset_ctx": "", "candle": "candles_5m"})
    if not shards["snapshot"]:
        return {"status": "UNMEASURABLE", "reason": "aucun instantané de vault au coffre : lancez le Certificateur"}
    identity = experiment_identity(root, {k: shards[k] for k in ("snapshot", "book_l2")}, config, f"positions|{price}")
    events, seen, rejects = cop.position_events_from_snapshots(load_snapshots(shards["snapshot"]))
    if price == "mids":
        panel = load_mid_panel(shards["allmids"], config.stale_price_ms)
        panel, _ = cop.alias_legacy_symbols(panel, events["coin"].unique())
        tier_prix = "prix observés en temps réel (allMids)"
    else:
        candles, identity["candles_source"] = bougies(root, shards)
        if candles is None:
            return {"status": "UNMEASURABLE", "reason": f"bougies absentes : {CANDLES_PATH.as_posix()}"}
        panel = cop.build_candle_panel(candles, interval_ms=CANDLE_INTERVAL_MS)
        tier_prix = "prix reconstruits (bougies 5 min récupérées après coup)"
    identity["corpus_tier"] = EVIDENCE_TIER_POSITIONS
    half_spreads = load_half_spreads(spread_shards(shards))
    funding = cop.build_funding_rates(load_funding(shards["asset_ctx"]), panel)
    print(f"[positions] {len(events):,} changements de position · {len(seen)} vaults · "
          f"{sum(len(v) for v in seen.values()):,} instantanés · panel {panel.px.shape}", flush=True)
    report = _jsonable(cop.run_position_replication_study(events, seen, panel, half_spreads, config,
                                                          funding_rates=funding))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-positions"
    result = {
        "run_id": run_id, "identity": identity, "rejects": dict(sorted(rejects.items())),
        "integrity_excluded_shards": excluded, "elapsed_seconds": round(time.time() - started, 1),
        "evidence_tier": EVIDENCE_TIER_POSITIONS, "price_tier": tier_prix, "report": report,
    }
    if write:
        out_dir = root / REPORT_DIR / run_id
        _atomic_write_json(out_dir / "resultat.json", result)
        inputs = report["inputs"]
        texte = render_retrospective_report(
            report, identity, result["rejects"],
            titre="# Réplication lente — PORTEFEUILLES OBSERVÉS des vaults",
            statut=f"- Statut des preuves : **{EVIDENCE_TIER_POSITIONS}** — positions observées, {tier_prix} ; exploratoire.",
            entrees=(f"{inputs['snapshots']:,} instantanés · {inputs['leaders']} vaults · {inputs['coins']} coins · "
                     f"{inputs['position_changes']:,} changements de position "
                     f"({(inputs['position_changes_priced_share'] or 0) * 100:.0f} % sur un coin avec prix) · "
                     f"prix `{inputs['price_provenance']}` sur {inputs['price_market_hours']:.0f} h."),
        )
        (out_dir / "RAPPORT.md").write_text(texte, encoding="utf-8")
        ledger = {
            "run_id": run_id, **identity, "evidence_tier": EVIDENCE_TIER_POSITIONS, "price_tier": tier_prix,
            "hypotheses_tested": report["hypotheses_tested"],
            "verdicts": [{"hypothesis": v["hypothesis"], "status": v["status"], "reason": v.get("reason")} for v in report["verdicts"]],
            "config": report["config"], "inputs": report["inputs"], "caveats": report["caveats"],
            "result_path": str((REPORT_DIR / run_id / "resultat.json").as_posix()),
            "paper_read_only": True, "real_execution": False, "economically_proven": False,
        }
        result["ledger_record_sha256"] = append_ledger(root / REPORT_DIR / "EXPERIENCES.ndjson", ledger)
        print(f"[positions] rapport : {out_dir / 'RAPPORT.md'}", flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--retrospectif", action="store_true",
                        help="réplication lente sur fills de backfill + bougies (historique reconstruit, non causal)")
    parser.add_argument("--positions", action="store_true",
                        help="réplication lente des portefeuilles OBSERVÉS des vaults (instantanés du coffre) ; "
                             "prix : bougies 5 min, ou allMids observés avec --prix mids")
    parser.add_argument("--retard-s", type=float, default=120.0,
                        help="avec --retrospectif : retard d'observation SUPPOSÉ après chaque fill (s)")
    parser.add_argument("--prix", choices=("mids", "prints"), default="mids",
                        help="mids = allMids observés (dex principal) ; prints = prix des transactions (repli, tous coins)")
    parser.add_argument("--workers", type=int, default=min(8, max(1, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--verifier-registre", action="store_true", help="revérifie la chaîne du registre et sort")
    parser.add_argument("--sans-ecriture", action="store_true", help="calcule sans écrire rapport, registre ni besoins")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.verifier_registre:
        status = verify_ledger(root / REPORT_DIR / "EXPERIENCES.ndjson")
        print(json.dumps(status, ensure_ascii=False))
        return 0 if status["status"] in {"VERIFIED", "EMPTY"} else 3
    if not (root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").is_file():
        print("[NO_GO] coffre LOCAL absent : lancez d'abord « Certificateur Coffre Fort.cmd ».")
        return 2
    if args.positions:
        result = run_positions(root, price="mids" if "--prix" in (argv or sys.argv) and args.prix == "mids" else "bougies",
                               write=not args.sans_ecriture)
        if "report" not in result:
            print(f"[{result['status']}] {result['reason']}")
            return 2
        for verdict in result["report"]["verdicts"]:
            print(f"[verdict positions] {verdict['hypothesis']}: {verdict['status']} — {verdict.get('reason')}")
        print("[FIN] étude sur portefeuilles observés (exploratoire) ; aucune rentabilité n'est prouvée.")
        return 0
    if args.retrospectif:
        result = run_retrospective(root, lag_s=args.retard_s, workers=args.workers, write=not args.sans_ecriture)
        if "report" not in result:
            print(f"[{result['status']}] {result['reason']}")
            return 2
        for verdict in result["report"]["verdicts"]:
            print(f"[verdict rétrospectif] {verdict['hypothesis']}: {verdict['status']} — {verdict.get('reason')}")
        print("[FIN] étude rétrospective (historique reconstruit) ; aucune rentabilité n'est prouvée.")
        return 0
    result = run(root, price=args.prix, workers=args.workers, config=cop.CopiabilityConfig(), write=not args.sans_ecriture)
    for verdict in result["report"]["verdicts"]:
        print(f"[verdict] {verdict['hypothesis']}: {verdict['status']} — {verdict.get('reason')}")
    print("[FIN] étude exploratoire (tier LOCAL) ; aucune rentabilité n'est prouvée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
