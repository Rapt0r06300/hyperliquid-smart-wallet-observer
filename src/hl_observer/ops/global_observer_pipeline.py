"""Pipeline Global Wallet Observer, bout en bout, sur données réelles (lecture seule, 0 réseau).

    sources de fills → normalisation → reconstruction → gate DESYNC → markouts causaux
                     → copyabilité (après NOS coûts) → scoring point-in-time → shortlist 8+2

Chaque étage peut refuser, et son refus est **compté** — c'est le seul moyen de savoir si un chiffre final
est petit parce que le marché est calme ou parce que la chaîne perd des données en route.

Deux gates non négociables :

* **DESYNC** — un wallet dont la reconstruction diverge de `start_pos` a des fills manquants. Son cycle de
  vie a l'air normal mais il est faux. Il est exclu du scoring, pas « corrigé ».
* **Source non autoritative** — un miroir non vérifié peut alimenter la plomberie, jamais le scoring.

Les markouts sont mesurés sur une bande de prix **postérieure au fill** : c'est une mesure de ce qui s'est
passé après, pas une entrée de décision. Un coin sans bande de prix n'a pas de markout : le wallet reste
`NON_MESURE`, il n'est pas noté 0.
"""
from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.following import fills_sources as FS
from hl_observer.following import wallet_reconstruction as WR
from hl_observer.following import wallet_scoring_shortlist as WS

SCHEMA_VERSION = "hypersmart.global_observer_pipeline.v1"
RAPPORT_RELPATH = Path("runtime") / "reports" / "global_observer.json"

#: Sources locales par défaut, de la plus riche à la moins riche.
SOURCES_DEFAUT: tuple[tuple[str, str], ...] = (
    ("runtime/data/vault_fills.jsonl", "vault_fills"),
    ("runtime/data/vault_fills_live.jsonl", "vault_fills_live"),
)
PRIX_DEFAUT = "runtime/data/hl_allmids_tape.jsonl"   # bande LARGE : tous les coins

#: Tolérance d'appariement d'un prix. Repli seulement : la vraie tolérance est DÉRIVÉE (voir ci-dessous).
TOLERANCE_PRIX_MS = 60_000.0

#: §3.1 — une tolérance FIXE de 60 s est incompatible avec un markout de 5 s : le prix utilisé pouvait être
#: postérieur de 12 horizons. La tolérance est donc dérivée de la cadence réelle du feed ET de l'horizon.
#: Règle PRÉ-ENREGISTRÉE : on accepte au plus une cotation de retard, et jamais plus d'une fraction de
#: l'horizon mesuré — sinon le "markout à h" mesure surtout le temps écoulé en trop.
FRACTION_HORIZON_MAX = 0.25
CADENCES_TOLEREES = 1.0


def tolerance_pour(horizon_ms: float, cadence_ms: float | None) -> float | None:
    """Tolérance temporelle admissible pour un horizon donné. `None` si la cadence l'interdit.

    Un horizon plus court que la cadence du feed n'est pas mesurable : le refuser vaut mieux que de
    prendre la cotation suivante et de l'appeler « markout à 100 ms ».
    """
    h = float(horizon_ms)
    if cadence_ms is None or float(cadence_ms) <= 0:
        return None
    c = float(cadence_ms)
    if h < c:
        return None
    return max(0.0, min(c * CADENCES_TOLEREES, h * FRACTION_HORIZON_MAX))


def _ts_ms(r: Mapping[str, Any]) -> int | None:
    """`ts_ms` en millisecondes, `ts` en secondes flottantes. Aucun repli sur `now`."""
    for cle, facteur in (("ts_ms", 1.0), ("ts", 1000.0)):
        v = r.get(cle)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v) * facteur
            if f == f and f > 0:
                return int(f)
    return None


def charger_prix(chemin: Path | str, *, coins: Iterable[str] | None = None,
                 max_lignes: int = 400_000) -> dict[str, dict[str, list]]:
    """Index {coin: {ts:[trié], mid:[]}}. Mémoire bornée par `max_lignes`.

    Deux formats acceptés, car le dépôt produit les deux :
      • **long**  — `{"coin": "BTC", "ts"|"ts_ms": ..., "mid"|"hl_mid"|"hl_bid"+"hl_ask": ...}`
      • **large** — `{"ts_ms": ..., "mids": {"BTC": ..., "ETH": ...}}` (bande allMids, tous les coins)
    La bande large est ce qui débloque la couverture : les BBO synchronisés ne portent que les majors,
    alors que les wallets suivis tradent surtout des alts.
    """
    voulus = {str(c).upper() for c in coins} if coins else None
    brut: dict[str, list[tuple[int, float]]] = {}
    p = Path(chemin)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for i, ligne in enumerate(fh):
            if i >= int(max_lignes):
                break
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                r = json.loads(ligne)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            ts = _ts_ms(r)
            if ts is None:
                continue

            mids = r.get("mids")
            if isinstance(mids, Mapping):                       # ── format large
                for nom, valeur in mids.items():
                    coin = str(nom).upper()
                    if coin.startswith("#") or coin.startswith("@"):
                        continue                                # indices internes, pas des coins
                    if voulus is not None and coin not in voulus:
                        continue
                    try:
                        mid = float(valeur)
                    except (TypeError, ValueError):
                        continue
                    if mid > 0:
                        brut.setdefault(coin, []).append((ts, mid))
                continue

            coin = str(r.get("coin") or "").upper()             # ── format long
            if not coin or (voulus is not None and coin not in voulus):
                continue
            mid = r.get("mid") if r.get("mid") is not None else r.get("hl_mid")
            if mid is None:
                bid, ask = r.get("hl_bid"), r.get("hl_ask")
                if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
                    mid = 0.5 * (float(bid) + float(ask))
            if not isinstance(mid, (int, float)) or mid <= 0:
                continue
            brut.setdefault(coin, []).append((ts, float(mid)))
    index: dict[str, dict[str, list]] = {}
    for coin, paires in brut.items():
        paires.sort(key=lambda x: x[0])
        index[coin] = {"ts": [p_[0] for p_ in paires], "mid": [p_[1] for p_ in paires]}
    return index


def _prix_a(index: Mapping[str, Mapping[str, Sequence]], coin: str, ts: float,
            *, tolerance_ms: float = TOLERANCE_PRIX_MS) -> float | None:
    """Premier prix observé **à ou après** `ts`, dans la tolérance. Sinon `None`."""
    detail = _prix_detaille(index, coin, ts, tolerance_ms=tolerance_ms)
    return None if detail is None else detail["prix"]


def _prix_detaille(index: Mapping[str, Mapping[str, Sequence]], coin: str, ts: float,
                   *, tolerance_ms: float) -> dict[str, Any] | None:
    """§3.1 — rend aussi l'horodatage CIBLE, celui RÉELLEMENT utilisé et l'erreur, pour que la mesure
    soit auditable au lieu d'être crue sur parole."""
    bloc = index.get(str(coin).upper())
    if not bloc or not bloc.get("ts"):
        return None
    temps = bloc["ts"]
    i = bisect_left(temps, int(ts))
    if i >= len(temps):
        return None
    erreur = float(temps[i]) - float(ts)
    if erreur > float(tolerance_ms):
        return None
    return {"prix": float(bloc["mid"][i]), "ts_cible": int(ts), "ts_utilise": int(temps[i]),
            "erreur_ms": round(erreur, 3), "tolerance_ms": round(float(tolerance_ms), 3)}


def markout_bps(index: Mapping[str, Mapping[str, Sequence]], *, coin: str, ts_ms: float, sens: int,
                horizon_ms: int, tolerance_ms: float | None = None,
                cadence_ms: float | None = None, detail: bool = False):
    """Markout signé du fill : ce que le prix a fait DANS le sens du wallet après `horizon_ms`.

    §3.1 — si `cadence_ms` est fourni, la tolérance est DÉRIVÉE (au plus une cotation de retard, et au plus
    `FRACTION_HORIZON_MAX` de l'horizon). Sans cadence, on retombe sur `tolerance_ms` explicite ou le repli
    historique — mais un appelant sérieux passe la cadence.
    """
    if sens not in (1, -1):
        return None
    if cadence_ms is not None:
        tol = tolerance_pour(horizon_ms, cadence_ms)
        if tol is None:
            return None                      # horizon sous la cadence : non mesurable, jamais approxime
    else:
        tol = float(TOLERANCE_PRIX_MS if tolerance_ms is None else tolerance_ms)
    d0 = _prix_detaille(index, coin, ts_ms, tolerance_ms=tol)
    d1 = _prix_detaille(index, coin, ts_ms + int(horizon_ms), tolerance_ms=tol)
    if d0 is None or d1 is None or d0["prix"] <= 0:
        return None
    valeur = round(sens * (d1["prix"] - d0["prix"]) / d0["prix"] * 1e4, 6)
    if not detail:
        return valeur
    return {"markout_bps": valeur, "entree": d0, "sortie": d1, "tolerance_derivee_ms": tol,
            "horizon_ms": int(horizon_ms), "cadence_ms": cadence_ms}


def executer(root: Path | str, *, sources: Sequence[tuple[str, str]] = SOURCES_DEFAUT,
             prix_relpath: str | None = PRIX_DEFAUT, horizon_markout_ms: int = 5_000,
             cout_ar_bps: float = 9.0, max_fills: int | None = None,
             max_lignes_prix: int = 400_000, min_episodes: int = WS.MIN_EPISODES) -> dict[str, Any]:
    """Exécute la chaîne complète et rend le rapport chiffré. Ne lève jamais sur donnée absente."""
    racine = Path(root)
    horodatage = datetime.now(timezone.utc).isoformat()
    stats = FS.StatsIngestion()

    fills: list[dict[str, Any]] = []
    inventaire_sources: list[dict[str, Any]] = []
    for relpath, source in sources:
        chemin = racine / relpath
        validation = FS.valider_schema(chemin, source=source, echantillon=200)
        inventaire_sources.append({"chemin": relpath, "source": source,
                                   "statut": validation["statut"],
                                   "autoritative": validation["autoritative"],
                                   "taux_normalisable": validation.get("taux_normalisable"),
                                   "start_pos_disponible": validation.get("start_pos_disponible")})
        if not validation.get("utilisable"):
            continue
        if not validation["autoritative"]:
            continue                     # bootstrap only : jamais dans le dataset de scoring
        reste = None if max_fills is None else max(0, int(max_fills) - len(fills))
        if reste == 0:
            break
        fills.extend(FS.flux_fills(chemin, source=source, stats=stats, max_fills=reste))

    rapport: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "genere_le": horodatage,
        "sources": inventaire_sources, "ingestion": stats.resume(),
        "horizon_markout_ms": int(horizon_markout_ms), "cout_ar_bps": float(cout_ar_bps),
        "paper_only": True, "real_execution": False,
    }
    if not fills:
        return {**rapport, "statut": "AUCUN_FILL_AUTORITATIF",
                "raison": "aucune source autoritative exploitable"}

    # ── reconstruction + gate DESYNC ────────────────────────────────────────────
    reconstruction = WR.reconstruire(fills)
    resume_reco = reconstruction.resume()
    par_wallet = WR.episodes_par_wallet(reconstruction)
    wallets_desync = {d["wallet"] for d in reconstruction.desyncs}
    wallets_fiables = [w for w in par_wallet if w not in wallets_desync]

    # ── markouts causaux ────────────────────────────────────────────────────────
    coins = {e["coin"] for e in reconstruction.episodes}
    index_prix = charger_prix(racine / prix_relpath, coins=coins,
                              max_lignes=max_lignes_prix) if prix_relpath else {}
    n_avec_markout = 0
    for episodes in par_wallet.values():
        for e in episodes:
            m = markout_bps(index_prix, coin=e["coin"], ts_ms=e["ts_ms"], sens=e["sens"],
                            horizon_ms=horizon_markout_ms)
            if m is not None:
                e["markouts_bps"] = {int(horizon_markout_ms): m}
                n_avec_markout += 1

    # ── scoring point-in-time + shortlist ───────────────────────────────────────
    as_of = max((e["ts_ms"] for e in reconstruction.episodes), default=0)
    scores = {w: WS.score_point_in_time(par_wallet[w], as_of_ms=as_of, cout_ar_bps=cout_ar_bps,
                                        horizon_markout_ms=int(horizon_markout_ms),
                                        min_episodes=int(min_episodes))
              for w in wallets_fiables}
    liste = WS.shortlist(scores)
    classement = WS.classer(scores)

    return {
        **rapport,
        "statut": "EXECUTE",
        "reconstruction": {k: resume_reco[k] for k in
                           ("n_episodes", "par_action", "n_twap", "n_wallets", "n_desyncs",
                            "n_doublons", "refus", "fiable")},
        "wallets": {
            "vus": resume_reco["n_wallets"],
            "en_desync": len(wallets_desync),
            "fiables": len(wallets_fiables),
            "scorables": sum(1 for s in scores.values() if s.get("score_copyable_bps") is not None),
            "eligibles_core": len(classement),
        },
        "markouts": {
            "horizon_ms": int(horizon_markout_ms),
            "n_episodes_avec_markout": n_avec_markout,
            "couverture": round(n_avec_markout / max(1, resume_reco["n_episodes"]), 4),
            "coins_couverts": sorted(set(index_prix) & coins),
            "coins_sans_prix": sorted(coins - set(index_prix))[:20],
        },
        "shortlist": {"core": liste["core"], "challengers": liste["challengers"],
                      "slots_utilises": liste["slots_utilises"], "limite_hl": liste["limite_hl"]},
        "meilleurs_scores_bps": [{"wallet": w, "score_copyable_bps": v} for w, v in classement[:10]],
    }


def ecrire_rapport(rapport: Mapping[str, Any], root: Path | str) -> Path:
    chemin = Path(root) / RAPPORT_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pipeline Global Wallet Observer (lecture seule, paper).")
    p.add_argument("--root", default=".")
    p.add_argument("--horizon-ms", type=int, default=5_000)
    p.add_argument("--cout-ar-bps", type=float, default=9.0)
    p.add_argument("--max-fills", type=int, default=None)
    p.add_argument("--max-lignes-prix", type=int, default=400_000)
    p.add_argument("--min-episodes", type=int, default=WS.MIN_EPISODES)
    a = p.parse_args(list(argv) if argv is not None else None)
    racine = Path(a.root).resolve()
    r = executer(racine, horizon_markout_ms=a.horizon_ms, cout_ar_bps=a.cout_ar_bps,
                 max_fills=a.max_fills, max_lignes_prix=a.max_lignes_prix,
                 min_episodes=a.min_episodes)
    chemin = ecrire_rapport(r, racine)
    print("statut:", r.get("statut"))
    if r.get("statut") == "EXECUTE":
        w, m, reco = r["wallets"], r["markouts"], r["reconstruction"]
        print("fills ingeres : %s (refuses %s)" % (r["ingestion"]["n_fills"], r["ingestion"]["n_refuses"]))
        print("cycles        : %s | TWAP %s | doublons %s" % (reco["par_action"], reco["n_twap"], reco["n_doublons"]))
        print("wallets       : vus %s | desync %s | fiables %s | scorables %s | eligibles CORE %s"
              % (w["vus"], w["en_desync"], w["fiables"], w["scorables"], w["eligibles_core"]))
        print("markouts      : couverture %s sur %s coins" % (m["couverture"], len(m["coins_couverts"])))
        print("shortlist     : CORE %s | CHALLENGERS %s" % (r["shortlist"]["core"], r["shortlist"]["challengers"]))
    print("rapport:", chemin)
    return 0


__all__ = ["SCHEMA_VERSION", "SOURCES_DEFAUT", "PRIX_DEFAUT", "TOLERANCE_PRIX_MS",
           "FRACTION_HORIZON_MAX", "CADENCES_TOLEREES", "tolerance_pour",
           "charger_prix", "markout_bps", "executer", "ecrire_rapport", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
