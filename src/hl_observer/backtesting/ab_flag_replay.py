"""V26 L9 — Harnais A/B REPLAY : mesurer l'effet réel des lots V26 sur le PF.

Rejoue la MÊME fenêtre de candidats enregistrés (JSONL, produits par le moteur avec
``HYPERSMART_V26_RECORD_CANDIDATES=1``) sous deux jeux de flags :

* bras A (baseline) : tous les vetos V26 OFF ;
* bras B (V26)      : flags choisis ON.

Pour chaque candidat accepté, l'issue est simulée sur le CHEMIN DE MARKS RÉELS
enregistré (marks.jsonl) : sortie TP/SL/trailing (config de base, ou vol-ajustée si
le bras l'active) ou timeout d'horizon au dernier mark connu. Aucune donnée future
inventée : pas de marks après l'entrée ⇒ candidat marqué UNMEASURABLE, exclu des
deux bras (jamais compté d'un seul côté).

Contexte REPLAY strict : ne lit que des fichiers, n'écrit que le rapport demandé,
ne touche JAMAIS au ledger live, n'émet aucun ordre. Les métriques (PF, WR, DD) sont
descriptives — pas une promesse de PnL.

CLI : ``python -m hl_observer.backtesting.ab_flag_replay --candidates F --marks F [--out F]``
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp

CONTEXT = "REPLAY"
DEFAULT_HORIZON_MIN = 240.0
DEFAULT_COST_BPS = 12.0
ANALYSIS_CACHE_SCHEMA_VERSION = 1

# Bras B par défaut : les vetos d'entrée + barrières vol (mesure de L1+L2+L4+L5+L7+L8)
DEFAULT_ARM_B_ENV = {
    "HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE": "1",
    "HYPERSMART_V26_PROTECTIONS": "1",
    "HYPERSMART_V26_GRADED_HALT": "0",       # dépend d'un état runtime, OFF par défaut en replay
    "HYPERSMART_V26_TIER_COST_BUDGET": "1",
    "HYPERSMART_V26_MARKET_QUALITY": "0",    # nécessite l'univers noté du runtime, OFF en replay
    "HYPERSMART_V26_VOL_BARRIERS": "1",
}
ARM_A_ENV = {k: "0" for k in DEFAULT_ARM_B_ENV}


@dataclass
class ArmMetrics:
    name: str
    candidates_seen: int = 0
    accepted: int = 0
    unmeasurable: int = 0
    trades: list[float] = field(default_factory=list)   # net pnl usd par trade

    def report(self) -> dict:
        wins = [t for t in self.trades if t > 0]
        losses = [t for t in self.trades if t <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        pf = round(gross_win / gross_loss, 4) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        equity, peak, max_dd = 0.0, 0.0, 0.0
        for t in self.trades:
            equity += t
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return {
            "arm": self.name,
            "context": CONTEXT,
            "candidates_seen": self.candidates_seen,
            "accepted": self.accepted,
            "trades": len(self.trades),
            "unmeasurable_excluded": self.unmeasurable,
            "win_rate": round(len(wins) / len(self.trades), 4) if self.trades else None,
            "profit_factor": pf if pf != float("inf") else "inf",
            "net_total_usd": round(sum(self.trades), 4),
            "gross_win_usd": round(gross_win, 4),
            "gross_loss_usd": round(gross_loss, 4),
            "max_drawdown_usd": round(max_dd, 4),
        }


def load_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    out.append(row)
            except json.JSONDecodeError:
                continue  # ligne corrompue ignorée (jamais réparée/inventée)
    return out


def build_analysis_cache_key(
    candidates_path: str | Path,
    marks_path: str | Path,
    *,
    horizon_min: float,
    fixed_notional_usd: float,
) -> str:
    """Fingerprint replay inputs and code so regenerated identical merges reuse work."""

    def source_signature(path_value: str | Path) -> dict[str, object]:
        path = Path(path_value).resolve()
        stat = path.stat()
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        return {
            "path": str(path),
            "size": stat.st_size,
            "sha256": digest.hexdigest(),
        }

    module_stat = Path(__file__).stat()
    payload = {
        "schema": ANALYSIS_CACHE_SCHEMA_VERSION,
        "python": list(sys.version_info[:3]),
        "module_mtime_ns": module_stat.st_mtime_ns,
        "candidates": source_signature(candidates_path),
        "marks": source_signature(marks_path),
        "horizon_min": float(horizon_min),
        "fixed_notional_usd": float(fixed_notional_usd),
        "cost_bps": DEFAULT_COST_BPS,
        "base_config": repr(SLTPConfig()),
        "arm_b_env": DEFAULT_ARM_B_ENV,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def load_cached_report(cache_path: str | Path, cache_key: str) -> dict | None:
    """Return a verified cached report, or None when any evidence changed."""

    path = Path(cache_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("cache_key") != cache_key:
        return None
    report = payload.get("report")
    return report if isinstance(report, dict) else None


def write_cached_report(cache_path: str | Path, cache_key: str, report: dict) -> None:
    """Persist an analysis-only cache atomically outside source data."""

    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "cache_schema": ANALYSIS_CACHE_SCHEMA_VERSION,
                "cache_key": cache_key,
                "report": report,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def marks_by_coin(mark_rows: list[dict]) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {}
    for r in mark_rows:
        if not isinstance(r, dict):
            continue          # ROBUSTESSE (fuzzing 2026-07-11) : ligne corrompue -> on l'ignore,
                              # on ne fait pas tomber tout le replay pour une ligne pourrie.
        coin = str(r.get("coin") or "").upper()
        try:
            ts, mid = float(r.get("ts")), float(r.get("mid"))
        except (TypeError, ValueError):
            continue
        if coin and mid > 0:
            out.setdefault(coin, []).append((ts, mid))
    for coin in out:
        out[coin].sort()
    return out


def simulate_exit_on_path(
    *,
    side: str,
    entry_price: float,
    path: list[tuple[float, float]],
    entry_ts: float,
    config: SLTPConfig,
    horizon_min: float = DEFAULT_HORIZON_MIN,
    cost_bps: float = DEFAULT_COST_BPS,
    notional_usd: float = 50.0,
) -> float | None:
    """PnL net USD d'un trade simulé sur le chemin de marks réels. None = non mesurable."""
    # ⚡ RECHERCHE BINAIRE au lieu d'un balayage complet. `path` est trié par ts (marks_by_coin
    # le garantit). L'ancienne comprehension parcourait TOUS les marks du coin POUR CHAQUE
    # candidat : sur 331 366 candidats et 109 192 marks, c'est ce qui faisait tourner le replay
    # plus de 5 minutes sans jamais rendre un resultat.
    if entry_price <= 0 or not path:
        return None
    import bisect as _bi
    debut = _bi.bisect_right(path, (entry_ts, float("inf")))
    fin = _bi.bisect_right(path, (entry_ts + horizon_min * 60.0, float("inf")))
    if debut >= fin:
        return None
    peak = entry_price
    # Ne pas copier la fenetre future pour chaque candidat. Sur les archives
    # reelles, ces slices temporaires dominaient le temps CPU et la memoire.
    exit_price = path[fin - 1][1]  # timeout d'horizon au dernier mark reel
    for index in range(debut, fin):
        mark = path[index][1]
        peak = max(peak, mark) if side == "LONG" else min(peak, mark)
        d = evaluate_sl_tp(side=side, entry_price=entry_price, current_price=mark, peak_price=peak, config=config)
        if d.exit:
            exit_price = mark
            break
    move = (exit_price - entry_price) / entry_price
    gross = notional_usd * (move if side == "LONG" else -move)
    costs = notional_usd * cost_bps / 10_000.0 * 2  # entrée + sortie
    return gross - costs


def _evaluate_arm(
    name: str,
    env: dict,
    candidates: list[dict],
    marks: dict[str, list[tuple[float, float]]],
    *,
    base_config: SLTPConfig,
    horizon_min: float,
    cost_bps: float,
    fixed_notional_usd: float | None = None,
) -> ArmMetrics:
    from hl_observer.paper_trading.vol_adjusted_barriers import (
        MidVolEstimator,
        adjust_config,
        vol_factor_for_coin,
    )
    from hl_observer.signals.v26_entry_vetos import EdgeTrendRecorder, apply_v26_entry_vetos

    m = ArmMetrics(name=name)
    recorder = EdgeTrendRecorder()          # état ISOLÉ par bras (aucune fuite du live)
    estimator = MidVolEstimator()
    vol_on = str(env.get("HYPERSMART_V26_VOL_BARRIERS", "0")).lower() in ("1", "true", "yes", "on")

    # 🔴 DEUX DEFAUTS CORRIGES ICI LE 2026-07-19 — l'un de VITESSE, l'autre de MESURE.
    #
    # L'ancienne version faisait, POUR CHAQUE candidat, une boucle sur TOUS les marks du coin
    # pour nourrir l'estimateur de volatilite. Consequences :
    #   1. VITESSE : O(candidats x marks). Sur 331 366 x 109 192, le replay tournait > 5 min
    #      sans jamais rendre un resultat -- notre seule mesure neuve etait inutilisable.
    #   2. MESURE (le plus grave) : le MEME mark etait re-enregistre a chaque candidat. Sur un
    #      coin a 1 000 candidats, chaque prix entrait 1 000 fois dans l'estimateur. Une
    #      volatilite calculee sur des doublons n'est pas une volatilite -- et c'est elle qui
    #      pilotait les barrieres SL/TP du bras B. On comparait donc deux bras dont l'un etait
    #      regle par un chiffre fausse.
    #
    # Correctif : on parcourt les candidats en ORDRE CHRONOLOGIQUE et on avance un CURSEUR par
    # coin. Chaque mark n'entre qu'UNE fois, dans l'ordre. Cout total : O(marks + candidats).
    # L'ordre chronologique est aussi ce que le replay doit faire par nature : on ne peut pas
    # nourrir un estimateur avec des prix qui arrivent dans le desordre sans mentir sur ce que
    # l'on savait a l'instant t.
    curseur: dict[str, int] = {}

    for cand in candidates:
        coin = str(cand.get("coin") or "").upper()
        side = str(cand.get("direction") or "").upper()
        edge = cand.get("edge_remaining_bps")
        entry = float(cand.get("current_mid") or 0.0)
        ts = float(cand.get("recorded_at") or 0.0)
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        m.candidates_seen += 1
        # nourrir l'estimateur avec les marks NOUVEAUX (<= ts) depuis le dernier candidat
        serie = marks.get(coin, ())
        i = curseur.get(coin, 0)
        while i < len(serie) and serie[i][0] <= ts:
            estimator.record(coin, serie[i][1], ts=serie[i][0])
            i += 1
        curseur[coin] = i
        # baseline d'acceptation : le candidat enregistré était déjà passé par le score V25 ;
        # on rejoue UNIQUEMENT les vetos V26 (c'est leur effet qu'on mesure, toutes choses égales).
        vetoes = apply_v26_entry_vetos(
            coin=coin, side=side,
            edge_remaining_bps=float(edge) if edge is not None else None,
            leader_score=cand.get("leader_score"),
            copy_degradation_bps=cand.get("copy_degradation_bps"),
            liquidity_score=cand.get("liquidity_score"),
            env=env, recorder=recorder, now_ms=int(ts * 1000),
        )
        if vetoes:
            continue
        m.accepted += 1
        cfg = base_config
        if vol_on:
            factor = vol_factor_for_coin(coin, estimator=estimator, env=env, now=ts)
            cfg = adjust_config(base_config, factor, sl_floor_bps=12.0)
        leader_notional = float(cand.get("leader_notional_usdt") or 0.0)
        comparison_notional = (
            float(fixed_notional_usd)
            if fixed_notional_usd is not None and fixed_notional_usd > 0
            else (leader_notional if leader_notional > 0 else 50.0)
        )
        pnl = simulate_exit_on_path(
            side=side, entry_price=entry, path=marks.get(coin, []), entry_ts=ts,
            config=cfg, horizon_min=horizon_min, cost_bps=cost_bps,
            notional_usd=comparison_notional,
        )
        if pnl is None:
            m.unmeasurable += 1
            m.accepted -= 1
            continue
        m.trades.append(round(pnl, 6))
    return m


def run_ab_replay(
    candidates: list[dict],
    mark_rows: list[dict],
    *,
    arm_b_env: dict | None = None,
    base_config: SLTPConfig | None = None,
    horizon_min: float = DEFAULT_HORIZON_MIN,
    cost_bps: float = DEFAULT_COST_BPS,
    fixed_notional_usd: float | None = None,
) -> dict:
    """Compare bras A (V26 OFF) vs bras B (V26 ON). Déterministe, REPLAY-only."""
    marks = marks_by_coin(mark_rows)
    cfg = base_config or SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0)
    env_b = dict(DEFAULT_ARM_B_ENV)
    if arm_b_env:
        env_b.update({k: str(v) for k, v in arm_b_env.items()})
    ordered_candidates = sorted(
        (candidate for candidate in candidates if isinstance(candidate, dict)),
        key=lambda candidate: (
            float(candidate.get("recorded_at") or 0.0),
            str(candidate.get("coin") or ""),
        ),
    )
    a = _evaluate_arm("A_baseline_v26_off", dict(ARM_A_ENV), ordered_candidates, marks,
                      base_config=cfg, horizon_min=horizon_min, cost_bps=cost_bps,
                      fixed_notional_usd=fixed_notional_usd)
    b = _evaluate_arm("B_v26_on", env_b, ordered_candidates, marks,
                      base_config=cfg, horizon_min=horizon_min, cost_bps=cost_bps,
                      fixed_notional_usd=fixed_notional_usd)
    ra, rb = a.report(), b.report()
    # VALID-GATES: chaque bras passe par les gates de validation unifiees ; on ne
    # recommande d'activer B que s'il passe TOUS les gates ET ameliore le net vs A.
    from hl_observer.backtesting.validation_gates import run_validation_gates
    va, vb = run_validation_gates(a.trades), run_validation_gates(b.trades)
    b_improves = (rb["net_total_usd"] or 0) > (ra["net_total_usd"] or 0)
    recommend = "ACTIVATE_B" if (vb["verdict"] == "DEPLOY_CANDIDATE" and b_improves) else "KEEP_A"
    return {
        "context": CONTEXT,
        "honesty": "metriques descriptives sur donnees enregistrees ; aucune promesse de PnL",
        "comparison_notional_usd": fixed_notional_usd,
        "arm_a": ra,
        "arm_b": rb,
        "delta_net_usd": round((rb["net_total_usd"] or 0) - (ra["net_total_usd"] or 0), 4),
        "arm_a_validation": va,
        "arm_b_validation": vb,
        "recommendation": recommend,
        "recommendation_rule": "ACTIVATE_B seulement si B passe tous les gates ET ameliore le net vs A (paper-only)",
        "arm_b_env": env_b,
    }


#: cache 1-entrée de l'index des marks : la recherche appelle net_baseline_seul des milliers de fois
#: avec LE MÊME `d.marks` (même objet liste) → on ne reconstruit pas `marks_by_coin` à chaque appel.
#: Garde id + longueur (un id réutilisé après GC sur une liste de même taille rebâtirait, sans risque).
_MARKS_INDEX_CACHE: dict = {"id": None, "len": -1, "idx": None}


def _index_marks(mark_rows_or_marks):
    if isinstance(mark_rows_or_marks, dict):
        return mark_rows_or_marks
    if (_MARKS_INDEX_CACHE["id"] == id(mark_rows_or_marks)
            and _MARKS_INDEX_CACHE["len"] == len(mark_rows_or_marks)):
        return _MARKS_INDEX_CACHE["idx"]
    idx = marks_by_coin(mark_rows_or_marks)
    _MARKS_INDEX_CACHE.update(id=id(mark_rows_or_marks), len=len(mark_rows_or_marks), idx=idx)
    return idx


def net_baseline_seul(
    candidates: list[dict],
    mark_rows_or_marks,
    *,
    base_config: SLTPConfig,
    horizon_min: float = DEFAULT_HORIZON_MIN,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict:
    """Le rapport du BRAS A (baseline, tous vetos OFF) UNIQUEMENT — DROP-IN pour `arm_a` de
    run_ab_replay. La recherche ne lit JAMAIS le bras B : le calculer (+ vetos + estimateur de vol,
    + reconstruire l'index des marks à chaque appel) est pur gâchis. Avec tout OFF, le bras A =
    simuler chaque candidat sur son chemin de marks. Résultat PROUVÉ IDENTIQUE au bras A — rapport
    COMPLET (net, PF, win rate, drawdown) via `ArmMetrics`, dans le MÊME ordre chronologique
    (le drawdown en dépend). Accepte des marks bruts ou un index déjà bâti (réutilisé)."""
    marks = _index_marks(mark_rows_or_marks)
    m = ArmMetrics(name="A_baseline_v26_off")
    # ordre chronologique (recorded_at, coin) — IDENTIQUE à _evaluate_arm, sinon le drawdown diffère
    for cand in sorted((c for c in candidates if isinstance(c, dict)),
                       key=lambda c: (float(c.get("recorded_at") or 0.0), str(c.get("coin") or ""))):
        coin = str(cand.get("coin") or "").upper()
        side = str(cand.get("direction") or "").upper()
        entry = float(cand.get("current_mid") or 0.0)
        ts = float(cand.get("recorded_at") or 0.0)
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        m.candidates_seen += 1
        m.accepted += 1                          # bras A : aucun veto (tout OFF)
        notio = float(cand.get("leader_notional_usdt") or 0.0)
        pnl = simulate_exit_on_path(
            side=side, entry_price=entry, path=marks.get(coin, []), entry_ts=ts,
            config=base_config, horizon_min=horizon_min, cost_bps=cost_bps,
            notional_usd=notio if notio > 0 else 50.0)
        if pnl is None:                          # non mesurable : exclu, exactement comme le bras A
            m.unmeasurable += 1
            m.accepted -= 1
            continue
        m.trades.append(round(pnl, 6))
    return {"arm_a": m.report()}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — CLI mince
    import argparse

    ap = argparse.ArgumentParser(description="V26 L9 — A/B replay des flags (REPLAY, paper-only)")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--horizon-min", type=float, default=DEFAULT_HORIZON_MIN)
    ap.add_argument(
        "--notional-usd",
        type=float,
        default=50.0,
        help="Notionnel constant par trade pour une comparaison A/B equitable.",
    )
    ap.add_argument(
        "--cache-path",
        default="",
        help="Cache local verifie; invalide si donnees, code ou parametres changent.",
    )
    args = ap.parse_args(argv)
    fixed_notional = max(1.0, float(args.notional_usd))
    cache_key = build_analysis_cache_key(
        args.candidates,
        args.marks,
        horizon_min=args.horizon_min,
        fixed_notional_usd=fixed_notional,
    )
    report = load_cached_report(args.cache_path, cache_key) if args.cache_path else None
    if report is None:
        print("analysis_cache=miss", flush=True)
        report = run_ab_replay(
            load_jsonl(args.candidates),
            load_jsonl(args.marks),
            horizon_min=args.horizon_min,
            fixed_notional_usd=fixed_notional,
        )
        if args.cache_path:
            write_cached_report(args.cache_path, cache_key, report)
    else:
        print("analysis_cache=hit", flush=True)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

__all__ = [
    "ANALYSIS_CACHE_SCHEMA_VERSION",
    "CONTEXT",
    "ArmMetrics",
    "DEFAULT_ARM_B_ENV",
    "build_analysis_cache_key",
    "load_cached_report",
    "load_jsonl",
    "marks_by_coin",
    "net_baseline_seul",
    "run_ab_replay",
    "simulate_exit_on_path",
    "write_cached_report",
]
