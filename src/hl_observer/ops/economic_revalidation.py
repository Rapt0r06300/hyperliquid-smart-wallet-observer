"""Bloc 18 — revalidation économique des stratégies sur la vérité canonique (lecture seule, 0 réseau).

Recalcule, avec **un seul dénominateur explicite par chiffre**, le jeu de métriques exigé par la roadmap :
`n | net bps/trade | net PnL | ROI (4 dénominateurs) | PF | max DD | expected shortfall | avg win/loss |
turnover | fees | fill ratio | capacité`, puis les enveloppes `BASE_CALIBRATED / ADVERSE_P95 / ADVERSE_P99 /
OPTIMISTIC_DIAGNOSTIC_ONLY`.

Trois règles qui décident de la valeur de ce module :

1. **Un épisode sans prix d'entrée ET de sortie exécutables n'a pas de PnL.** Il est compté comme
   `NON_MESURABLE` et exclu — jamais valorisé à 0, ce qui diluerait la moyenne vers le beau.
2. **Aucun dénominateur implicite.** Le ROI est publié quatre fois (equity de départ, marge moyenne, marge
   pic, exposition brute) ; un dénominateur inconnu rend `None`, pas une valeur de repli.
3. **L'optimiste ne classe rien.** L'enveloppe `OPTIMISTIC_DIAGNOSTIC_ONLY` est marquée non promouvable :
   une stratégie n'est jamais « bonne » parce que seul son scénario favorable est positif.

Ce module ne promet aucun résultat : il rend mesurable ce qui l'est, et nomme ce qui ne l'est pas.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.economic_revalidation.v1"
RAPPORT_RELPATH = Path("runtime") / "reports" / "economic_revalidation.json"

#: Dégradations adverses PRÉ-ENREGISTRÉES, en bps de coût aller-retour SUPPLÉMENTAIRE.
#: Déclarées `ASSUMED` : aucun ordre réel n'existe, donc la queue de coûts n'est pas observable.
DEGRADATIONS_ADVERSES_BPS: dict[str, float] = {"ADVERSE_P95": 6.0, "ADVERSE_P99": 12.0}
#: Gain retiré dans l'enveloppe optimiste (diagnostic seulement).
GAIN_OPTIMISTE_BPS = 3.0

LEDGERS_CONNUS: dict[str, str] = {
    "carry_paper": "runtime/data/carry_paper_ledger.jsonl",
    "raw_probe": "runtime/data/raw_probe_ledger.jsonl",
    "experimental_paper_v2": "runtime/data/experimental_paper_V2_ledger.jsonl",
}


@dataclass(frozen=True, slots=True)
class Episode:
    """Aller-retour clos, avec ses deux prix EXÉCUTABLES. Sans eux, il n'existe pas économiquement."""

    strategie: str
    coin: str
    sens: int                      # +1 long, -1 short
    notional_usd: float
    prix_entree: float
    prix_sortie: float
    frais_usd: float = 0.0
    marge_usd: float | None = None
    ts_open_ms: int | None = None
    ts_close_ms: int | None = None

    def pnl_brut_usd(self) -> float:
        return self.sens * (self.prix_sortie - self.prix_entree) / self.prix_entree * self.notional_usd

    def pnl_net_usd(self) -> float:
        return self.pnl_brut_usd() - float(self.frais_usd)

    def net_bps(self) -> float:
        return self.pnl_net_usd() / self.notional_usd * 1e4


def _f(valeur: Any) -> float | None:
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _positif(valeur: Any) -> float | None:
    v = _f(valeur)
    return v if v is not None and v > 0 else None


# ════════════════════════════ normalisation ════════════════════════════
def normaliser_episodes(lignes: Iterable[Mapping[str, Any]], *, strategie: str) -> dict[str, Any]:
    """Appaire OPEN/CLOSE par (coin, sens). Tout ce qui n'a pas ses deux prix devient `NON_MESURABLE`."""
    ouvertes: dict[tuple[str, int], list[dict[str, Any]]] = {}
    episodes: list[Episode] = []
    rejets: dict[str, int] = {}

    def rejeter(motif: str) -> None:
        rejets[motif] = rejets.get(motif, 0) + 1

    for ligne in lignes:
        evt = str(ligne.get("evt") or ligne.get("kind") or ligne.get("type") or "").upper()
        coin = str(ligne.get("coin") or "")
        if not coin:
            rejeter("COIN_ABSENT")
            continue
        sens_brut = ligne.get("sens")
        sens = int(sens_brut) if sens_brut in (1, -1, "1", "-1") else 0
        prix = _positif(ligne.get("prix_entree") if evt in {"OPEN", "RENFORT"} else ligne.get("prix_sortie"))
        if prix is None:
            prix = _positif(ligne.get("price") or ligne.get("prix"))
        notional = _positif(ligne.get("notional_usd") or ligne.get("notional_usdt"))

        if evt in {"OPEN", "RENFORT", "ADD"}:
            if prix is None or notional is None:
                rejeter("OUVERTURE_SANS_PRIX_OU_NOTIONNEL")
                continue
            ouvertes.setdefault((coin, sens), []).append(
                {"prix": prix, "notional": notional, "ts": ligne.get("ts_ms"),
                 "frais": _f(ligne.get("frais_usd")) or 0.0, "marge": _f(ligne.get("marge_usd"))})
        elif evt in {"CLOSE", "REDUCE", "EXIT"}:
            pile = ouvertes.get((coin, sens)) or []
            if not pile:
                rejeter("FERMETURE_ORPHELINE")
                continue
            ouverture = pile.pop(0)
            if prix is None:
                rejeter("FERMETURE_SANS_PRIX_EXECUTABLE")
                continue
            episodes.append(Episode(
                strategie=strategie, coin=coin, sens=sens or 1,
                notional_usd=ouverture["notional"], prix_entree=ouverture["prix"], prix_sortie=prix,
                frais_usd=(ouverture["frais"] or 0.0) + (_f(ligne.get("frais_usd")) or 0.0),
                marge_usd=ouverture["marge"], ts_open_ms=ouverture["ts"], ts_close_ms=ligne.get("ts_ms"),
            ))
        else:
            rejeter("EVENEMENT_HORS_CYCLE")

    non_fermees = sum(len(v) for v in ouvertes.values())
    if non_fermees:
        rejets["POSITION_ENCORE_OUVERTE"] = non_fermees
    return {"episodes": episodes, "rejets": rejets, "n_episodes": len(episodes),
            "n_non_mesurables": sum(rejets.values())}


# ════════════════════════════ métriques ════════════════════════════
def _drawdown_max(nets: Sequence[float]) -> float:
    cumul = pic = dd = 0.0
    for x in nets:
        cumul += x
        pic = max(pic, cumul)
        dd = min(dd, cumul - pic)
    return dd


def _expected_shortfall(nets: Sequence[float], *, alpha: float = 0.05) -> float | None:
    if len(nets) < 20:
        return None
    tries = sorted(nets)
    k = max(1, int(len(tries) * alpha))
    return round(statistics.mean(tries[:k]), 6)


def metriques(episodes: Sequence[Episode], *, starting_equity_usd: float | None = None,
              marge_moyenne_usd: float | None = None, marge_pic_usd: float | None = None,
              capacite_usd: float | None = None, fill_ratio: float | None = None) -> dict[str, Any]:
    """Jeu complet de métriques. Chaque dénominateur absent rend `None`, jamais une valeur de repli."""
    n = len(episodes)
    base: dict[str, Any] = {"n_episodes": n, "capacite_usd": capacite_usd, "fill_ratio": fill_ratio}
    if n == 0:
        return {**base, "statut": "AUCUNE_DONNEE_MESURABLE", "net_pnl_usd": None, "net_bps_par_trade": None,
                "profit_factor": None, "max_drawdown_usd": None, "roi": {}, "turnover_usd": None,
                "fees_usd": None, "expected_shortfall_usd": None, "avg_win_usd": None, "avg_loss_usd": None}

    nets = [e.pnl_net_usd() for e in episodes]
    net_total = sum(nets)
    gains = [x for x in nets if x > 0]
    pertes = [x for x in nets if x < 0]
    turnover = sum(2.0 * e.notional_usd for e in episodes)
    fees = sum(float(e.frais_usd) for e in episodes)
    exposition_brute = sum(e.notional_usd for e in episodes)

    def roi(denominateur: float | None) -> float | None:
        d = _positif(denominateur)
        return round(net_total / d, 8) if d is not None else None

    return {
        **base,
        "statut": "MESURE",
        "net_pnl_usd": round(net_total, 6),
        "net_bps_par_trade": round(statistics.mean([e.net_bps() for e in episodes]), 4),
        "profit_factor": (round(sum(gains) / abs(sum(pertes)), 4) if pertes else None),
        "profit_factor_note": None if pertes else "aucune perte : PF non defini, pas infini",
        "max_drawdown_usd": round(_drawdown_max(nets), 6),
        "expected_shortfall_usd": _expected_shortfall(nets),
        "avg_win_usd": round(statistics.mean(gains), 6) if gains else None,
        "avg_loss_usd": round(statistics.mean(pertes), 6) if pertes else None,
        "hit_rate": round(len(gains) / n, 4),
        "turnover_usd": round(turnover, 6),
        "fees_usd": round(fees, 6),
        "roi": {
            "ROI_starting_equity": roi(starting_equity_usd),
            "ROI_avg_margin_locked": roi(marge_moyenne_usd),
            "ROI_peak_margin_locked": roi(marge_pic_usd),
            "return_on_gross_exposure": roi(exposition_brute),
        },
        "gross_exposure_usd": round(exposition_brute, 6),
    }


def enveloppes(episodes: Sequence[Episode], **kw: Any) -> dict[str, Any]:
    """BASE / ADVERSE_P95 / ADVERSE_P99 / OPTIMISTIC. L'optimiste est explicitement non promouvable."""
    def decale(bps: float) -> list[Episode]:
        return [Episode(e.strategie, e.coin, e.sens, e.notional_usd, e.prix_entree, e.prix_sortie,
                        frais_usd=e.frais_usd + e.notional_usd * bps / 1e4, marge_usd=e.marge_usd,
                        ts_open_ms=e.ts_open_ms, ts_close_ms=e.ts_close_ms) for e in episodes]

    out: dict[str, Any] = {"BASE_CALIBRATED": metriques(episodes, **kw)}
    for nom, bps in DEGRADATIONS_ADVERSES_BPS.items():
        out[nom] = {**metriques(decale(bps), **kw), "degradation_bps": bps, "origine": "ASSUMED"}
    out["OPTIMISTIC_DIAGNOSTIC_ONLY"] = {
        **metriques(decale(-GAIN_OPTIMISTE_BPS), **kw),
        "gain_retire_bps": GAIN_OPTIMISTE_BPS, "promouvable": False,
        "note": "diagnostic seulement : une strategie n'est jamais bonne parce que l'optimiste est positif",
    }
    return out


# ════════════════════════════ exécution sur les ledgers réels ════════════════════════════
def _lire_jsonl(chemin: Path, *, max_lignes: int = 200_000) -> list[dict[str, Any]]:
    lignes: list[dict[str, Any]] = []
    try:
        with chemin.open("r", encoding="utf-8", errors="replace") as fh:
            for i, brute in enumerate(fh):
                if i >= max_lignes:
                    break
                brute = brute.strip()
                if not brute:
                    continue
                try:
                    obj = json.loads(brute)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    lignes.append(obj)
    except OSError:
        return []
    return lignes


def revalider(root: Path | str, *, starting_equity_usd: float = 1000.0,
              ledgers: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Revalide chaque ledger connu. Ledger absent ou non appariable ⇒ statut explicite, jamais un zéro."""
    racine = Path(root)
    table = dict(ledgers or LEDGERS_CONNUS)
    rapport: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "starting_equity_usd": starting_equity_usd,
        "degradations_adverses_bps": dict(DEGRADATIONS_ADVERSES_BPS),
        "avertissement": "les degradations adverses sont ASSUMED : sans ordre reel, la queue de couts n'est pas observable",
        "paper_only": True, "real_execution": False,
        "strategies": {},
    }
    for strategie, relpath in sorted(table.items()):
        chemin = racine / relpath
        if not chemin.exists():
            rapport["strategies"][strategie] = {"statut": "LEDGER_ABSENT", "chemin": relpath}
            continue
        lignes = _lire_jsonl(chemin)
        norm = normaliser_episodes(lignes, strategie=strategie)
        eps = norm["episodes"]
        rapport["strategies"][strategie] = {
            "chemin": relpath, "n_lignes": len(lignes), "n_episodes": norm["n_episodes"],
            "rejets": norm["rejets"],
            "statut": "MESURE" if eps else "AUCUN_EPISODE_MESURABLE",
            "enveloppes": enveloppes(eps, starting_equity_usd=starting_equity_usd) if eps else None,
        }
    return rapport


def ecrire_rapport(rapport: Mapping[str, Any], root: Path | str) -> Path:
    chemin = Path(root) / RAPPORT_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revalidation economique (lecture seule, paper-only).")
    parser.add_argument("--root", default=".")
    parser.add_argument("--starting-equity", type=float, default=1000.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    rapport = revalider(Path(args.root).resolve(), starting_equity_usd=float(args.starting_equity))
    chemin = ecrire_rapport(rapport, Path(args.root).resolve())
    for nom, bloc in rapport["strategies"].items():
        print("%-24s %-26s episodes=%s" % (nom, bloc.get("statut"), bloc.get("n_episodes")))
    print("rapport: %s" % chemin)
    return 0


__all__ = ["SCHEMA_VERSION", "DEGRADATIONS_ADVERSES_BPS", "GAIN_OPTIMISTE_BPS", "LEDGERS_CONNUS",
           "Episode", "normaliser_episodes", "metriques", "enveloppes", "revalider", "ecrire_rapport", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
