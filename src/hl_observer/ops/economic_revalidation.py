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
    position_id: str | None = None          # §4.2 — la sortie pointe vers l'exposition reellement ouverte
    quantite: float | None = None
    frais_mesures: bool = True              # §4.4 — False => frais ABSENTS du ledger, pas nuls

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
@dataclass
class _Lot:
    """Exposition ouverte pour un (coin, sens). Un REDUCE n'en ferme qu'une PART."""

    quantite: float
    prix_moyen: float
    frais: float = 0.0
    frais_mesures: bool = True
    position_id: str = ""
    ts_open_ms: int | None = None


def _qte(notional: float | None, prix: float | None) -> float | None:
    if notional is None or prix is None or prix <= 0:
        return None
    return notional / prix


def normaliser_episodes(lignes: Iterable[Mapping[str, Any]], *, strategie: str) -> dict[str, Any]:
    """§4.1 — moteur de LOTS : un REDUCE ne ferme que la quantite reduite.

    L'ancien normaliseur traitait tout REDUCE comme la fermeture d'un OPEN entier : un leader qui allege
    de 10 % voyait 100 % de sa position realisee, et le reliquat disparaissait. Ici :
    quantite ouverte, prix moyen pondere, PnL realise **sur la seule quantite fermee**, reliquat conserve,
    frais proportionnels, et FLIP = fermeture de l'ancienne quantite + ouverture du reliquat oppose.

    §4.3 — chaque fermeture orpheline est classee par CAUSE au lieu d'etre comptee en bloc.
    §4.4 — des frais absents du ledger ne valent JAMAIS zero : l'episode porte `frais_mesures=False`.
    """
    lots: dict[tuple[str, int], _Lot] = {}
    episodes: list[Episode] = []
    rejets: dict[str, int] = {}
    causes_orphelines: dict[str, int] = {}
    compteur = {"n": 0}

    def rejeter(motif: str) -> None:
        rejets[motif] = rejets.get(motif, 0) + 1

    def nouvelle_position(coin: str, sens: int) -> str:
        compteur["n"] += 1
        return "%s:%s:%s:%04d" % (strategie, coin, "L" if sens > 0 else "S", compteur["n"])

    ordonnees = []
    for ligne in lignes:
        ts = _f(ligne.get("ts_ms")) or _f(ligne.get("recorded_at_ms")) or 0.0
        ordonnees.append((ts, ligne))
    ordonnees.sort(key=lambda x: x[0])

    for _ts, ligne in ordonnees:
        evt = str(ligne.get("evt") or ligne.get("kind") or ligne.get("type") or "").upper()
        coin = str(ligne.get("coin") or "")
        if not coin:
            rejeter("COIN_ABSENT")
            continue
        brut_sens = ligne.get("sens")
        sens = int(brut_sens) if brut_sens in (1, -1, "1", "-1") else 0
        ouverture = evt in {"OPEN", "ADD", "RENFORT", "INCREASE"}
        fermeture = evt in {"CLOSE", "REDUCE", "EXIT", "FLIP"}
        if not ouverture and not fermeture:
            rejeter("EVENEMENT_HORS_CYCLE")
            continue

        prix = _positif(ligne.get("prix_entree") if ouverture else ligne.get("prix_sortie"))
        if prix is None:
            prix = _positif(ligne.get("price") or ligne.get("prix"))
        notional = _positif(ligne.get("notional_usd") or ligne.get("notional_usdt"))
        frais_ligne = _f(ligne.get("frais_usd"))
        frais_mesures = frais_ligne is not None
        ts_ms = ligne.get("ts_ms") or ligne.get("recorded_at_ms")

        if ouverture:
            if prix is None or notional is None:
                rejeter("OUVERTURE_SANS_PRIX_OU_NOTIONNEL")
                continue
            q = _qte(notional, prix)
            cle = (coin, sens or 1)
            lot = lots.get(cle)
            if lot is None:
                lots[cle] = _Lot(quantite=q, prix_moyen=prix, frais=(frais_ligne or 0.0),
                                 frais_mesures=frais_mesures, position_id=nouvelle_position(coin, sens or 1),
                                 ts_open_ms=ts_ms)
            else:
                total = lot.quantite + q
                lot.prix_moyen = (lot.prix_moyen * lot.quantite + prix * q) / total if total > 0 else prix
                lot.quantite = total
                lot.frais += (frais_ligne or 0.0)
                lot.frais_mesures = lot.frais_mesures and frais_mesures
            continue

        # ── fermeture (REDUCE partiel, CLOSE, FLIP)
        cle = (coin, sens or 1)
        lot = lots.get(cle)
        if lot is None:
            rejeter("FERMETURE_ORPHELINE")
            # §4.3 : nommer la cause au lieu de compter en bloc
            if prix is None:
                cause = "ORPHELINE_ET_SANS_PRIX"
            elif sens == 0:
                cause = "SENS_ABSENT_APPARIEMENT_IMPOSSIBLE"
            elif any(c == coin for c, _s in lots):
                cause = "SENS_OPPOSE_OUVERT_SEULEMENT"
            else:
                cause = "OPEN_HORS_FENETRE_OU_LEDGER_TRONQUE"
            causes_orphelines[cause] = causes_orphelines.get(cause, 0) + 1
            continue
        if prix is None:
            rejeter("FERMETURE_SANS_PRIX_EXECUTABLE")
            continue

        q_demandee = _qte(notional, prix) if notional is not None else lot.quantite
        q_fermee = min(q_demandee, lot.quantite)
        if q_fermee <= 0:
            rejeter("FERMETURE_DE_QUANTITE_NULLE")
            continue
        part = q_fermee / lot.quantite if lot.quantite > 0 else 1.0
        frais_part = lot.frais * part + (frais_ligne or 0.0)
        episodes.append(Episode(
            strategie=strategie, coin=coin, sens=sens or 1,
            notional_usd=q_fermee * lot.prix_moyen, prix_entree=lot.prix_moyen, prix_sortie=prix,
            frais_usd=frais_part, ts_open_ms=lot.ts_open_ms, ts_close_ms=ts_ms,
            position_id=lot.position_id, quantite=q_fermee,
            frais_mesures=lot.frais_mesures and frais_mesures,
        ))
        lot.frais -= lot.frais * part
        lot.quantite -= q_fermee
        if lot.quantite <= 1e-12:
            del lots[cle]

        # FLIP : l'exces au-dela de la position ouvre le sens oppose
        exces = q_demandee - q_fermee
        if exces > 1e-12:
            oppose = (coin, -(sens or 1))
            lots[oppose] = _Lot(quantite=exces, prix_moyen=prix, frais=0.0, frais_mesures=frais_mesures,
                                position_id=nouvelle_position(coin, -(sens or 1)), ts_open_ms=ts_ms)

    non_fermees = sum(1 for _ in lots)
    if non_fermees:
        rejets["POSITION_ENCORE_OUVERTE"] = non_fermees
    return {"episodes": episodes, "rejets": rejets, "n_episodes": len(episodes),
            "n_non_mesurables": sum(rejets.values()),
            "causes_fermetures_orphelines": causes_orphelines,
            "positions_ouvertes_restantes": [
                {"coin": c, "sens": s, "quantite": round(l.quantite, 10), "position_id": l.position_id}
                for (c, s), l in sorted(lots.items())],
            "frais_non_mesures": sum(1 for e in episodes if not e.frais_mesures)}


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
        "fees_statut": ("FEES_UNMEASURABLE" if any(not e.frais_mesures for e in episodes)
                        else "FEES_MESURES"),
        "fees_note": ("des frais absents du ledger ne valent pas zero : le net ci-dessus est un net "
                      "HORS frais reels" if any(not e.frais_mesures for e in episodes) else None),
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


def _capacite_du_lot(racine: Path, episodes: Sequence[Episode], carnet_relpath: str | None) -> dict[str, Any] | None:
    """Étape 2/3 — joint la profondeur exécutable causale. Absence de carnet ⇒ `None`, jamais une estimation."""
    if not carnet_relpath:
        return None
    chemin = racine / carnet_relpath
    if not chemin.exists() or not episodes:
        return None
    try:
        from hl_observer.ops.episode_capacity import charger_carnets, enrichir_episodes
        index = charger_carnets(chemin, coins={e.coin for e in episodes})
        resume = enrichir_episodes(episodes, index)
    except Exception:  # noqa: BLE001 — une capacité manquante ne doit jamais casser la revalidation
        return None
    resume.pop("details", None)          # le détail par épisode reste disponible via le module dédié
    return resume


def revalider(root: Path | str, *, starting_equity_usd: float = 1000.0,
              ledgers: Mapping[str, str] | None = None,
              carnet_relpath: str | None = "runtime/data/carnet_venues.jsonl") -> dict[str, Any]:
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
        capacite = _capacite_du_lot(racine, eps, carnet_relpath)
        rapport["strategies"][strategie] = {
            "chemin": relpath, "n_lignes": len(lignes), "n_episodes": norm["n_episodes"],
            "rejets": norm["rejets"],
            "causes_fermetures_orphelines": norm.get("causes_fermetures_orphelines"),
            "positions_ouvertes_restantes": norm.get("positions_ouvertes_restantes"),
            "frais_non_mesures": norm.get("frais_non_mesures"),
            "statut": "MESURE" if eps else "AUCUN_EPISODE_MESURABLE",
            "capacite": capacite,
            "enveloppes": enveloppes(
                eps, starting_equity_usd=starting_equity_usd,
                capacite_usd=(capacite or {}).get("capacite_mediane_usd"),
                fill_ratio=(capacite or {}).get("fill_ratio_median"),
            ) if eps else None,
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
