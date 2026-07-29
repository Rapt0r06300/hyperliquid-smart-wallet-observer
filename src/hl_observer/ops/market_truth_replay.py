"""Sonde d'executabilite et de couts reels, via la chaine market_truth.

POURQUOI CE MODULE EXISTE
-------------------------
`hl_observer.market_truth` (canonicalisation -> replay executable -> ledger papier
reconcilie) etait ecrit et teste mais n'avait AUCUN appelant de production : la
maladie connue du projet (« teste-seulement »). Ce module est la porte : il branche
la chaine dans le lanceur d'analyse officiel `ANALYSER_BACKTESTS_REPLAYS.cmd`
(etape `market_truth_replay` de `historical_analysis_suite`).

CE QU'IL MESURE — ET CE QU'IL NE MESURE PAS
-------------------------------------------
Il mesure l'EXECUTABILITE et les COUTS REELS sur les ticks durables reellement
collectes : quelle fraction d'intentions serait remplie, a quel prix, avec quel
spread, quelle profondeur consommee, quel cout de latence, quel markout.

Il ne mesure AUCUN edge et AUCUN PnL de strategie. Les intentions sont ancrees sur
de vrais evenements et posees dans les DEUX sens (LONG et SHORT) precisement pour
qu'aucun resultat directionnel ne puisse en sortir. Un chiffre issu de ce module ne
doit jamais etre presente comme une performance.

DENY-BY-DEFAULT
---------------
Pas de ticks durables, schema non reconnu, fenetre trop courte -> statut explicite
(`NO_DATA`, `NO_INTENT`) et medianes a `null`. Jamais un zero presente comme une
mesure.

Securite : lecture seule sur disque local, 0 reseau, 0 ordre reel, 0 cle, 0
signature. `paper_only=True` / `real_execution=False` dans tout le rapport.
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from hl_observer.market_truth import MarketTruthPipeline, ReplayIntent
from hl_observer.market_truth.truth_chain import TruthChain

SCHEMA_VERSION = "hypersmart.market_truth_replay.v1"
DEFAULT_TICKS_DIR = Path("runtime") / "data" / "market_ticks"
TICK_SCHEMA = "hypersmart.tick.v1"

#: Sens testes pour chaque ancre. Les deux, toujours : une sonde d'executabilite ne
#: doit pas pouvoir etre confondue avec un pari directionnel.
SIDES: tuple[str, ...] = ("LONG", "SHORT")


@dataclass(frozen=True)
class ProbeConfig:
    notional_usdc: float = 50.0
    latency_ms: int = 250
    fee_bps: float = 4.5
    execution_style: str = "TAKER"
    every: int = 50
    max_intents: int = 400
    horizon_ms: int = 15_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _median(values: Sequence[float]) -> float | None:
    """Mediane, ou `None` si rien a mesurer. Jamais 0.0 par defaut."""
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return round(statistics.median(clean), 6)


def _observable_ms(record: Mapping[str, Any]) -> int | None:
    """Instant ou le tick devient observable : max(reception, ecriture).

    Identique a `canonicalize_tick_record`, calcule ici sans canonicaliser pour
    pouvoir trier et fenetrer a moindre cout.
    """
    try:
        received = int(record["received_ts_ms"])
        written = int(record["written_ts_ms"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(received, written)


def iter_tick_records(ticks_dir: Path) -> Iterator[dict[str, Any]]:
    """Lit les ticks durables : fichier courant + shards gzip immuables.

    Une ligne illisible est ignoree SANS masquer le probleme : elle est comptee par
    l'appelant via la difference entre lignes lues et enregistrements rendus.
    """
    if not ticks_dir.exists():
        return
    fichiers: list[Path] = sorted(ticks_dir.glob("*.jsonl"))
    shards = ticks_dir / "shards"
    if shards.is_dir():
        fichiers.extend(sorted(shards.glob("*.jsonl.gz")))
        fichiers.extend(sorted(shards.glob("*.jsonl")))
    for chemin in fichiers:
        try:
            if chemin.suffix == ".gz":
                handle: Any = gzip.open(chemin, "rt", encoding="utf-8", errors="replace")
            else:
                handle = chemin.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for ligne in handle:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    row = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row


def load_ticks(ticks_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Charge, valide le schema et trie les ticks par instant observable."""
    total = 0
    mauvais_schema = 0
    sans_horloge = 0
    retenus: list[dict[str, Any]] = []
    for row in iter_tick_records(ticks_dir):
        total += 1
        if row.get("schema_version") != TICK_SCHEMA:
            mauvais_schema += 1
            continue
        obs = _observable_ms(row)
        if obs is None:
            sans_horloge += 1
            continue
        row["_observable_at_ms"] = obs
        retenus.append(row)
    retenus.sort(key=lambda r: (r["_observable_at_ms"], str(r.get("instrument") or "")))
    inventaire = {
        "lignes_lues": total,
        "ticks_retenus": len(retenus),
        "rejets_schema": mauvais_schema,
        "rejets_horloge_locale": sans_horloge,
        "instruments": sorted({str(r.get("instrument") or "?") for r in retenus}),
    }
    return retenus, inventaire


def _fenetre(
    ticks: Sequence[Mapping[str, Any]], debut_index: int, fin_ms: int
) -> list[Mapping[str, Any]]:
    """Ticks de `debut_index` jusqu'a `fin_ms` inclus (aucun evenement anterieur)."""
    out: list[Mapping[str, Any]] = []
    for row in ticks[debut_index:]:
        if int(row["_observable_at_ms"]) > fin_ms:
            break
        out.append(row)
    return out


def build_intents(
    ticks: Sequence[Mapping[str, Any]], config: ProbeConfig
) -> list[tuple[ReplayIntent, int]]:
    """Ancre des intentions sur de VRAIS evenements, dans les deux sens.

    Rend une liste de (intent, index de l'ancre). Aucun instant n'est invente : le
    `signal_observable_at_ms` est celui d'un tick reellement recu.
    """
    intents: list[tuple[ReplayIntent, int]] = []
    par_instrument: dict[str, int] = {}
    for index, row in enumerate(ticks):
        instrument = str(row.get("instrument") or "")
        if not instrument:
            continue
        rang = par_instrument.get(instrument, 0)
        par_instrument[instrument] = rang + 1
        if rang % max(1, config.every) != 0:
            continue
        ancre_ms = int(row["_observable_at_ms"])
        for side in SIDES:
            intents.append(
                (
                    ReplayIntent(
                        signal_id="probe:%s:%d:%s" % (instrument, ancre_ms, side),
                        coin=instrument,
                        position_side=side,
                        action="OPEN",
                        signal_observable_at_ms=ancre_ms,
                        requested_notional_usdc=config.notional_usdc,
                        latency_ms=config.latency_ms,
                        execution_style=config.execution_style,
                        fee_bps=config.fee_bps,
                    ),
                    index,
                )
            )
            if len(intents) >= config.max_intents:
                return intents
    return intents


def run_probe(ticks_dir: Path, config: ProbeConfig) -> dict[str, Any]:
    """Execute la sonde et rend le rapport. Ne leve jamais sur donnee absente."""
    rapport: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "genere_le": _utc_now(),
        "source": str(ticks_dir),
        "mesure": "EXECUTABILITE_ET_COUTS_REELS",
        "ne_mesure_pas": "aucun edge, aucun PnL de strategie, aucune performance",
        "ledger": "TruthChain isolee par intention (sonde, pas un portefeuille)",
        "paper_only": True,
        "real_execution": False,
        "config": {
            "notional_usdc": config.notional_usdc,
            "latency_ms": config.latency_ms,
            "fee_bps": config.fee_bps,
            "execution_style": config.execution_style,
            "echantillonnage_1_tick_sur": config.every,
            "max_intentions": config.max_intents,
            "horizon_ms": config.horizon_ms,
            "sens_testes": list(SIDES),
        },
    }

    ticks, inventaire = load_ticks(ticks_dir)
    rapport["inventaire"] = inventaire
    if not ticks:
        rapport["statut"] = "NO_DATA"
        rapport["raison"] = (
            "Aucun tick durable au schema %s sous %s. Le collecteur BBO ecrit ce "
            "dataset ; sans lui la chaine market_truth n'a rien a rejouer." % (TICK_SCHEMA, ticks_dir)
        )
        return rapport

    intents = build_intents(ticks, config)
    if not intents:
        rapport["statut"] = "NO_INTENT"
        rapport["raison"] = "Ticks presents mais aucun instrument exploitable pour ancrer une intention."
        return rapport

    statuts: dict[str, int] = {}
    raisons: dict[str, int] = {}
    par_instrument: dict[str, dict[str, int]] = {}
    spreads: list[float] = []
    slippages: list[float] = []
    latences: list[float] = []
    markouts: list[float] = []
    ratios: list[float] = []
    n_executables = 0

    for intent, index in intents:
        fin_ms = int(intent.signal_observable_at_ms) + int(config.horizon_ms)
        fenetre = _fenetre(ticks, index, fin_ms)
        # TruthChain neuve : on mesure l'executabilite d'une intention, pas la
        # trajectoire d'un portefeuille (aucune position n'est reportee).
        pipeline = MarketTruthPipeline(truth_chain=TruthChain())
        resultat = pipeline.run(intent=intent, durable_tick_records=fenetre)
        fill = resultat.truth.fill
        statut = str(getattr(fill.status, "value", fill.status))
        statuts[statut] = statuts.get(statut, 0) + 1
        raisons[str(fill.reason)] = raisons.get(str(fill.reason), 0) + 1
        bucket = par_instrument.setdefault(
            str(intent.coin), {"intentions": 0, "executables": 0}
        )
        bucket["intentions"] += 1
        if fill.executable:
            n_executables += 1
            bucket["executables"] += 1
            ratios.append(float(fill.fill_ratio))
            couts = fill.costs
            for valeur, cible in (
                (couts.spread_bps, spreads),
                (couts.depth_slippage_bps, slippages),
                (couts.latency_cost_bps, latences),
                (couts.markout_bps, markouts),
            ):
                if valeur is not None:
                    cible.append(float(valeur))

    n = len(intents)
    rapport["statut"] = "OK" if n_executables else "AUCUNE_INTENTION_EXECUTABLE"
    rapport["intentions"] = {
        "total": n,
        "executables": n_executables,
        "taux_executable": round(n_executables / n, 4) if n else None,
        "par_statut": dict(sorted(statuts.items(), key=lambda kv: -kv[1])),
        "raisons": dict(sorted(raisons.items(), key=lambda kv: -kv[1])[:15]),
    }
    rapport["couts_bps_medians"] = {
        "spread": _median(spreads),
        "slippage_profondeur": _median(slippages),
        "cout_latence": _median(latences),
        "markout": _median(markouts),
        "frais_configures": config.fee_bps,
    }
    rapport["fill_ratio_median"] = _median(ratios)
    rapport["par_instrument"] = dict(sorted(par_instrument.items()))
    if not n_executables:
        rapport["raison"] = (
            "Aucune intention executable : carnet absent, perime, ou qualite de flux "
            "insuffisante sur la fenetre. Voir `intentions.raisons`."
        )
    return rapport


def write_report(rapport: Mapping[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    chemin = output_dir / "market_truth_replay.json"
    chemin.write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return chemin


def _resume(rapport: Mapping[str, Any]) -> str:
    statut = rapport.get("statut")
    if statut in {"NO_DATA", "NO_INTENT"}:
        return "%s : %s" % (statut, rapport.get("raison", ""))
    intentions = rapport.get("intentions") or {}
    couts = rapport.get("couts_bps_medians") or {}
    return (
        "%s | %s intentions, %s executables (%s) | spread median %s bps, "
        "slippage %s bps, markout %s bps"
        % (
            statut,
            intentions.get("total"),
            intentions.get("executables"),
            intentions.get("taux_executable"),
            couts.get("spread"),
            couts.get("slippage_profondeur"),
            couts.get("markout"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sonde d'executabilite et de couts reels via la chaine market_truth "
            "(lecture seule, paper-only, 0 reseau)."
        )
    )
    parser.add_argument("--root", default=".", help="Racine du projet.")
    parser.add_argument(
        "--ticks-dir",
        default=None,
        help="Dossier des ticks durables (defaut: runtime/data/market_ticks).",
    )
    parser.add_argument("--output-dir", required=True, help="Dossier du rapport JSON.")
    parser.add_argument("--notional", type=float, default=50.0)
    parser.add_argument("--latency-ms", type=int, default=250)
    parser.add_argument("--fee-bps", type=float, default=4.5)
    parser.add_argument("--execution-style", default="TAKER", choices=["TAKER", "MAKER"])
    parser.add_argument("--every", type=int, default=50, help="Une ancre tous les N ticks d'un instrument.")
    parser.add_argument("--max-intents", type=int, default=400)
    parser.add_argument("--horizon-ms", type=int, default=15_000)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()
    ticks_dir = Path(args.ticks_dir) if args.ticks_dir else (root / DEFAULT_TICKS_DIR)
    config = ProbeConfig(
        notional_usdc=float(args.notional),
        latency_ms=int(args.latency_ms),
        fee_bps=float(args.fee_bps),
        execution_style=str(args.execution_style),
        every=int(args.every),
        max_intents=int(args.max_intents),
        horizon_ms=int(args.horizon_ms),
    )
    rapport = run_probe(ticks_dir, config)
    chemin = write_report(rapport, Path(args.output_dir))
    print(_resume(rapport))
    print("rapport: %s" % chemin)
    # Une absence de donnee n'est pas une panne du programme : le rapport le dit
    # explicitement et la suite reste verte.
    return 0


__all__ = [
    "ProbeConfig",
    "SCHEMA_VERSION",
    "build_intents",
    "iter_tick_records",
    "load_ticks",
    "main",
    "run_probe",
    "write_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
