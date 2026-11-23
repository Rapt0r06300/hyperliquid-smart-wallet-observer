r"""Récolte des données externes GRATUITES, recoupement avec les nôtres, puis mise au coffre par le certificateur.

    tools\python\python.exe tools\coffre_donnees_externes.py            tout : récolte, recoupement, coffre
    tools\python\python.exe tools\coffre_donnees_externes.py --plan     état et reste à faire ; aucun réseau, aucune écriture

Décision de l'opérateur (23/11/2026) : « si ces données sont viables, fiables, backtestables et replayables, elles
sont autorisées à aller dans le coffre-fort », et « il faudra que ces données soient utiles au labo ». Donc :

1. RÉCOLTE incrémentale à empreintes vérifiées : Ironflow (funding, open interest + mark/oracle, liquidations,
   bougies 1 h) et les 1ers du mois gratuits de Tardis (trades et carnet ; BTC, ETH, HYPE). Rien de payant.
2. RECOUPEMENT, dex par dex, avec NOS données (cache de recherche issu du coffre), sur des seuils fixés ici AVANT
   de lire les résultats (``SEUILS``). Un dex qui ne se recoupe pas, ou qui n'a rien en commun avec nous, n'entre pas.
3. VERSEMENT là où le coffre n'a rien d'Alina : une heure de funding ou une bougie que nous avons déjà n'est pas
   versée (le coffre dédoublonne ruban par ruban, pas entre sources) ; open interest et trades, seulement AVANT
   notre première observation. Chaque ligne est pré-certifiée par le certificateur du coffre ; au-delà de 0,1 %
   de quarantaine, le fichier entier est refusé. Une archive ``runtime/history/externe_*_<chiffres>.jsonl.gz`` par
   fichier source, écrite sous un nom temporaire puis renommée. Chaque ligne : ``data_origin: EXTERNAL_HISTORICAL``,
   ``causal_observation: false``, ``causal_forward_eligible: false`` et son fichier source.
4. SCELLEMENT par ``tools/sceller_coffre_local.py`` (le portail habituel) ; l'index du coffre porte ``provenance``.

Ce que le labo en fait : le funding comble les heures qui manquent au calcul du portage (Alina reste prioritaire à
la même heure) ; bougies, open interest, liquidations et trades sont des signaux de contexte comptés À PART
(``signaux_externes_par_famille``). CE QUI N'ENTRE PAS : le carnet Tardis (il n'a pas d'heure de réception par
Alina ; la fabriquer serait un maquillage) ; il reste dans ``runtime/history/tardis`` pour la recherche.
LECTURE SEULE côté marché : aucun ordre, aucune clé, aucune écriture hors de ``runtime/history`` et du coffre.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import time
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterator

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hl_observer.datasets.coffre_certifie import (  # noqa: E402
    ORIGINE_EXTERNE, QUARANTAINE, certifier_record, detecter_famille)

HISTOIRE = Path("runtime") / "history"
IRON, TARD = HISTOIRE / "ironflow", HISTOIRE / "tardis"
CACHE = Path("runtime") / "research_lab" / "data" / "goal2_cache"
INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
MANIFESTES = Path("runtime") / "coffre_certifie" / "local" / "manifests"
VERROU = Path("runtime") / "data" / "coffre_certificateur.lock"
ETAT = HISTOIRE / "coffre_externe_etat.json"
RAPPORT = HISTOIRE / "coffre_externe_rapport.json"
RECOUPEMENT = HISTOIRE / "coffre_externe_recoupement.json"
DEBUT_DEFAUT = "2026-04-01"            # l'historique de nos leaders commence fin avril
COINS_TARDIS = ("BTC", "ETH", "HYPE")
QUARANTAINE_MAX = 0.001
H = 3_600_000

#: jeu -> (tronc du ruban, famille du coffre)
JEUX = {
    "funding": ("externe_ironflow_funding_1h", "funding_history"),
    "candles-1h": ("externe_ironflow_candles_1h", "candle"),
    "open-interest": ("externe_ironflow_asset_ctx", "asset_ctx"),
    "liquidations": ("externe_ironflow_liquidations", "liquidation"),
    "tardis-trades": ("externe_tardis_trades", "trades_marche"),
}
PROVENANCE = {"data_origin": ORIGINE_EXTERNE, "causal_observation": False, "causal_forward_eligible": False}

#: Seuils de recoupement, fixés AVANT toute mesure. Ce sont des contrôles d'erreur GROSSIÈRE (unité, coin mal
#: nommé, décalage d'une heure), pas de précision : un groupe qui les rate n'entre pas, il n'est pas « ajusté ».
SEUILS = {
    "funding": "taux identique (< 1e-9) sur >= 99,9 % des heures communes",
    "candles-1h": "close à moins de 10 bps du nôtre sur >= 99,9 % des heures communes",
    "open-interest": "mark (daté de la FIN de son heure, voir OI_DECALAGE_MS) à moins de 10 bps (médiane) de "
                     "l'ouverture de notre bougie ; > 100 bps sur <= 2 %",
    "liquidations": "prix moyen dans [bas ; haut] de notre bougie de l'heure (± 0,2 %) pour >= 99 %",
    "tardis-trades": "prix dans [bas ; haut] de notre bougie de l'heure (± 0,05 %) pour >= 99,9 %",
}
PAIRES_MIN = 100

#: 23/11/2026 -- L'OPEN INTEREST D'IRONFLOW EST DATÉ DU DÉBUT DE L'HEURE, MAIS MESURÉ À SA FIN. Mesure sur octobre
#: (126 539 paires, dex natif) : le mark d'une ligne datée t est à 1,89 bps (médiane) de la CLÔTURE de notre bougie
#: [t ; t + 1 h], à 3,92 bps de l'ouverture de la bougie suivante, et à 46 bps de l'ouverture de la sienne. Lue
#: telle quelle, la ligne donnerait le marché UNE HEURE À L'AVANCE : une fuite du futur dans tout backtest. Le
#: recoupement l'a refusée ; elle entre datée t + 1 h. Ce sens est le sens PRUDENT : si l'heure vraie était t, la
#: donnée arriverait une heure en retard, jamais en avance. L'étiquette d'origine reste dans `ironflow_horodatage_ms`.
OI_DECALAGE_MS = H


def _lire(chemin: Path) -> Any:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _remplacer(tmp: Path, chemin: Path, essais: int = 8) -> None:
    """``os.replace`` qui RÉESSAIE : sous Windows, un antivirus ou l'indexeur qui tient la cible un instant fait
    échouer le renommage (WinError 5, vu le 23/11 sur l'état). Au-delà des essais, l'erreur remonte : jamais muette."""
    for i in range(essais):
        try:
            os.replace(tmp, chemin)
            return
        except PermissionError:
            if i == essais - 1:
                raise
            time.sleep(0.25 * (i + 1))


def _ecrire_atomique(chemin: Path, donnees: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    _remplacer(tmp, chemin)


def _f(x: Any) -> float | None:
    """Nombre fini ou None (un NaN écrit en JSON serait illisible pour d'autres lecteurs)."""
    if x is None:
        return None
    x = float(x)
    return None if x != x or x in (float("inf"), float("-inf")) else x


def dex_de(coin: str) -> str:
    return coin.split(":", 1)[0] if ":" in coin else ""


def ms_de(iso: str) -> int:
    return int(dt.datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------------------- sources validées

def sources_validees(root: Path) -> list[dict[str, Any]]:
    """Les seuls fichiers au statut EXTERNAL_VALIDATED des deux manifestes, ordre stable."""
    out: list[dict[str, Any]] = []
    man = _lire(root / IRON / "MANIFESTE.json") or {"fichiers": {}}
    for cle in sorted(man["fichiers"]):
        m = man["fichiers"][cle]
        jeu = cle.split("/", 1)[0]
        if m.get("statut") != "EXTERNAL_VALIDATED" or jeu not in JEUX:
            continue
        if jeu == "liquidations" and "/events/" not in cle:
            continue                         # les fills de liquidation doublonneraient les événements
        out.append({"jeu": jeu, "cle": cle, "chemin": root / IRON / cle, "version": str(m.get("sha256")),
                    "bornes": (int(m["ts_min_ms"]), int(m["ts_max_ms"]))})
    man = _lire(root / TARD / "MANIFESTE.json") or {"fichiers": {}}
    for cle in sorted(man["fichiers"]):
        m = man["fichiers"][cle]
        if not cle.startswith("trades/") or m.get("statut") != "EXTERNAL_VALIDATED":
            continue
        out.append({"jeu": "tardis-trades", "cle": cle, "chemin": root / TARD / cle,
                    "version": f"{m.get('octets')}|{m.get('recupere_utc')}",
                    "bornes": (int(m["ts_min_us"]) // 1000, int(m["ts_max_us"]) // 1000)})
    return out


# --------------------------------------------------------------------------- lecture des fichiers source

def _ts_ms(colonne) -> Any:
    unite = colonne.type.unit
    v = colonne.cast("int64").to_numpy()
    return v * 1000 if unite == "s" else v // {"ms": 1, "us": 1000, "ns": 1_000_000}[unite]


def lignes_ironflow(chemin: Path) -> Iterator[dict[str, Any]]:
    """Lignes brutes d'un Parquet Ironflow, groupe par groupe ; ``ts`` en ms UTC exactes."""
    import pyarrow.parquet as pq

    f = pq.ParquetFile(chemin)
    for i in range(f.num_row_groups):
        t = f.read_row_group(i)
        ts = _ts_ms(t.column("timestamp"))
        cols = {n: t.column(n).to_pylist() for n in t.schema.names if n != "timestamp"}
        for k in range(t.num_rows):
            r = {n: v[k] for n, v in cols.items()}
            r["ts"] = int(ts[k])
            yield r


def lignes_tardis(chemin: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        e = next(lecteur)
        i = {k: e.index(k) for k in ("timestamp", "local_timestamp", "id", "side", "price", "amount")}
        for ligne in lecteur:
            yield {"ts": int(ligne[i["timestamp"]]) // 1000, "local": int(ligne[i["local_timestamp"]]) // 1000,
                   "id": ligne[i["id"]], "side": ligne[i["side"]], "price": float(ligne[i["price"]]),
                   "amount": float(ligne[i["amount"]])}


def convertir(jeu: str, r: dict[str, Any], base: dict[str, Any], coin_tardis: str = "") -> tuple[dict | None, str]:
    """Ligne brute -> enregistrement au format du coffre, ou (None, motif d'exclusion NOMMÉ)."""
    t = r["ts"]
    if jeu == "funding":
        return {**base, "coin": str(r["coin"]), "ts_ms": t, "funding": _f(r["funding_rate"]),
                "premium": _f(r.get("premium"))}, ""
    if jeu == "candles-1h":
        if r.get("market_class") != "perp":
            return None, "bougie_spot_sans_nom_hyperliquid"
        return {**base, "coin": str(r["coin"]), "interval": "1h", "open_ts_ms": t, "open": _f(r["open"]),
                "high": _f(r["high"]), "low": _f(r["low"]), "close": _f(r["close"]), "volume": _f(r["volume"]),
                "trades": r.get("trades")}, ""
    if jeu == "open-interest":
        oi = _f(r.get("open_interest"))
        if oi is None or oi < 0:
            return None, "open_interest_negatif_ou_absent"
        mark, oracle = _f(r.get("mark_price")), _f(r.get("oracle_price"))
        if not ((mark or 0) > 0 or (oracle or 0) > 0):
            # 23/11/2026 : règle AJOUTÉE APRÈS que la porte de quarantaine a refusé 5 fichiers (avril-août, jusqu'à
            # 33 % de lignes sans mark ni oracle). Ces lignes n'ont jamais été recoupées (le contrôle ne compare que
            # les lignes qui ont un mark) ; elles sont exclues, nommées, jamais réparées.
            return None, "ni_mark_ni_oracle_jamais_recoupe"
        return {**base, "coin": str(r["coin"]), "ts_ms": t + OI_DECALAGE_MS, "ironflow_horodatage_ms": t,
                "mark": _f(r.get("mark_price")),
                "oracle": _f(r.get("oracle_price")), "open_interest": oi,
                "open_interest_usd": _f(r.get("open_interest_usd"))}, ""
    if jeu == "liquidations":
        marche = str(r["market"])
        if not marche.endswith("-PERP"):
            return None, "liquidation_spot_sans_nom_hyperliquid"
        return {**base, "coin": marche[:-5], "ts_ms": t, "px": _f(r["avg_price"]), "sz": _f(r["size"]),
                "side": r.get("position_side"), "wallet": r.get("wallet"), "notional_usd": _f(r.get("notional_usd")),
                "fills": r.get("fills"), "hash": r.get("tx_hash"),
                # une position liquidée = un événement : (transaction, wallet) est unique
                "stable_event_id": f"{r.get('tx_hash')}:{r.get('wallet')}"}, ""
    if jeu == "tardis-trades":
        return {**base, "coin": coin_tardis, "exchange_ts_ms": t, "price": r["price"], "size": r["amount"],
                "aggressor_side": "BUY" if r["side"] == "buy" else "SELL", "tid": r["id"],
                # horloge de CAPTURE de Tardis, nommée comme telle : ce n'est PAS une réception par Alina
                "tardis_local_ts_ms": r["local"]}, ""
    return None, "jeu_inconnu"


# --------------------------------------------------------------------------- recoupement

def _nos_bougies(root: Path):
    import pandas as pd

    d = pd.read_parquet(root / CACHE / "candles_1h.parquet", columns=["coin", "t_ms", "o", "h", "l", "c"])
    d["t_ms"] = d["t_ms"].astype("int64")
    return d


def _ironflow_df(sources: list[dict], jeu: str, depuis_ms: int, colonnes: list[str]):
    import pandas as pd
    import pyarrow.parquet as pq

    morceaux = []
    for s in sources:
        if s["jeu"] != jeu or s["bornes"][1] < depuis_ms:
            continue
        t = pq.read_table(s["chemin"], columns=["timestamp", *colonnes])
        d = t.drop(["timestamp"]).to_pandas()
        d["t_ms"] = _ts_ms(t.column("timestamp"))
        morceaux.append(d[d["t_ms"] >= depuis_ms])
    return pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame(columns=["t_ms", *colonnes])


def _par_groupe(m, critere: Callable[[Any], dict]) -> dict[str, dict]:
    """Applique ``critere`` (-> mesures + 'admis') à chaque groupe ; un groupe trop maigre n'est pas admis."""
    out = {}
    for g, sous in m.groupby("groupe"):
        if len(sous) < PAIRES_MIN:
            out[str(g)] = {"paires": int(len(sous)), "admis": False, "motif": f"moins de {PAIRES_MIN} paires communes"}
            continue
        out[str(g)] = {"paires": int(len(sous)), **critere(sous)}
    return out


def recouper(root: Path, sources: list[dict], depuis_ms: int) -> dict[str, dict]:
    """Par jeu : {groupe: mesures + admis}. Un jeu non mesurable n'admet AUCUN groupe (fail-closed)."""
    import pandas as pd

    res: dict[str, dict] = {}
    try:
        nous = _nos_bougies(root)
    except (OSError, ValueError, KeyError) as exc:
        return {j: {"_statut": f"NON_MESURABLE : nos bougies illisibles ({type(exc).__name__})"} for j in JEUX}

    def funding() -> dict:
        ours = pd.read_parquet(root / CACHE / "funding_1h.parquet")
        tcol = "ts_ms" if "ts_ms" in ours else "t_ms"
        rcol = next(c for c in ("funding", "fundingRate", "funding_rate", "taux", "rate") if c in ours)
        ours = pd.DataFrame({"coin": ours["coin"], "heure": (ours[tcol].astype("int64") + H // 2) // H,
                             "nous": ours[rcol].astype(float)})
        ir = _ironflow_df(sources, "funding", depuis_ms, ["coin", "funding_rate"])
        ir["heure"] = (ir["t_ms"].astype("int64") + H // 2) // H
        m = ir.merge(ours, on=["coin", "heure"], how="inner")
        m["groupe"] = m["coin"].map(dex_de)

        def crit(s):
            part = float(((s["funding_rate"].astype(float) - s["nous"]).abs() < 1e-9).mean())
            return {"part_identique": round(part, 6), "admis": part >= 0.999}
        return _par_groupe(m, crit)

    def bougies() -> dict:
        ir = _ironflow_df(sources, "candles-1h", depuis_ms, ["coin", "close", "market_class"])
        ir = ir[ir["market_class"] == "perp"]
        m = ir.merge(nous, on=["coin", "t_ms"], how="inner")
        m["groupe"] = m["coin"].map(dex_de)

        def crit(s):
            part = float((1e4 * (s["close"].astype(float) / s["c"].astype(float) - 1.0)).abs().gt(10).mean())
            return {"part_au_dela_10_bps": round(part, 6), "admis": part <= 0.001}
        return _par_groupe(m, crit)

    def oi() -> dict:
        ir = _ironflow_df(sources, "open-interest", depuis_ms, ["coin", "mark_price"])
        ir["t_ms"] = ir["t_ms"].astype("int64") + OI_DECALAGE_MS      # l'heure où la mesure a vraiment été prise
        m = ir.merge(nous, on=["coin", "t_ms"], how="inner")
        m = m[(m["o"].astype(float) > 0) & (m["mark_price"].astype(float) > 0)].copy()
        m["groupe"] = m["coin"].map(dex_de)

        def crit(s):
            e = (1e4 * (s["mark_price"].astype(float) / s["o"].astype(float) - 1.0)).abs()
            med, loin = float(e.median()), float((e > 100).mean())
            return {"ecart_median_bps": round(med, 3), "part_au_dela_100_bps": round(loin, 6),
                    "admis": med <= 10 and loin <= 0.02}
        return _par_groupe(m, crit)

    def liquidations() -> dict:
        ir = _ironflow_df(sources, "liquidations", depuis_ms, ["market", "avg_price"])
        ir = ir[ir["market"].astype(str).str.endswith("-PERP")].copy()
        ir["coin"] = ir["market"].astype(str).str[:-5]
        ir["t_ms"] = ir["t_ms"].astype("int64") // H * H
        m = ir.merge(nous, on=["coin", "t_ms"], how="inner")
        m["groupe"] = m["coin"].map(dex_de)

        def crit(s):
            px = s["avg_price"].astype(float)
            part = float(((px >= s["l"].astype(float) * 0.998) & (px <= s["h"].astype(float) * 1.002)).mean())
            return {"part_dans_la_bougie": round(part, 6), "admis": part >= 0.99}
        return _par_groupe(m, crit)

    def tardis() -> dict:
        lignes = []
        for s in sources:
            if s["jeu"] != "tardis-trades" or s["bornes"][1] < depuis_ms:
                continue
            coin = Path(s["cle"]).name.split(".")[0]
            for k, r in enumerate(lignes_tardis(s["chemin"])):
                if k % 50 == 0:                                  # un trade sur 50 suffit à un contrôle grossier
                    lignes.append((coin, r["ts"] // H * H, r["price"]))
        ir = pd.DataFrame(lignes, columns=["coin", "t_ms", "price"])
        ir["t_ms"] = ir["t_ms"].astype("int64")
        m = ir.merge(nous, on=["coin", "t_ms"], how="inner")
        m["groupe"] = m["coin"]                                  # un groupe par coin

        def crit(s):
            px = s["price"].astype(float)
            part = float(((px >= s["l"].astype(float) * 0.9995) & (px <= s["h"].astype(float) * 1.0005)).mean())
            return {"part_dans_la_bougie": round(part, 6), "admis": part >= 0.999}
        return _par_groupe(m, crit)

    for jeu, fn in (("funding", funding), ("candles-1h", bougies), ("open-interest", oi),
                    ("liquidations", liquidations), ("tardis-trades", tardis)):
        try:
            res[jeu] = fn()
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            res[jeu] = {"_statut": f"NON_MESURABLE : {type(exc).__name__}: {exc}"}
    return res


def groupes_admis(recoupement: dict[str, dict]) -> dict[str, set[str]]:
    return {jeu: {g for g, v in r.items() if not g.startswith("_") and isinstance(v, dict) and v.get("admis")}
            for jeu, r in recoupement.items()}


# --------------------------------------------------------------------------- ce que le coffre a déjà (Alina)

def deja_au_coffre(root: Path, depuis_ms: int) -> dict[str, Any]:
    """Clés des données d'ALINA déjà au coffre (jamais celles d'une source externe) et premières observations."""
    index = _lire(root / INDEX) or {"shards": []}
    alina = [s for s in index.get("shards", []) if isinstance(s, dict) and s.get("provenance") != ORIGINE_EXTERNE]
    debut: dict[str, int | None] = {}
    for fam in ("asset_ctx", "trades_marche"):
        ts = [s["ts_min_ms"] for s in alina if s.get("famille") == fam and isinstance(s.get("ts_min_ms"), int)]
        debut[fam] = min(ts) if ts else None
    cles: dict[str, set] = {"funding": set(), "candles-1h": set(), "liquidations": set()}

    def lire(s: dict) -> Iterator[dict]:
        if isinstance(s.get("ts_max_ms"), int) and s["ts_max_ms"] < depuis_ms:
            return
        try:
            with gzip.open(root / s["shard"], "rt", encoding="utf-8") as f:
                for ligne in f:
                    try:
                        yield json.loads(ligne)
                    except ValueError:
                        continue
        except OSError:
            return

    for s in alina:
        fam = s.get("famille")
        if fam == "funding_history":
            for x in lire(s):
                if isinstance(x.get("ts_ms"), int):
                    cles["funding"].add((x.get("coin"), (x["ts_ms"] + H // 2) // H))
        elif fam == "candle" and ("candles_1h" in str(s.get("shard")) or "candle_lane" in str(s.get("shard"))):
            for x in lire(s):
                if x.get("interval") == "1h" and isinstance(x.get("open_ts_ms"), int):
                    cles["candles-1h"].add((x.get("coin"), x["open_ts_ms"] // H))
        elif fam == "liquidation":
            for x in lire(s):
                if x.get("hash"):
                    cles["liquidations"].add((x.get("coin"), x.get("hash")))
    return {"cles": cles, "debut_alina": debut, "rubans_scelles": rubans_scelles(index)}


def nom_sans_extension(nom: str) -> str:
    return nom[:-3] if nom.endswith(".gz") else nom


def rubans_scelles(index: dict) -> dict[str, int]:
    """{ruban externe (sans .gz) : lignes déposées} d'après l'index du coffre : c'est le COFFRE qui dit ce qui y est."""
    out: dict[str, int] = {}
    for s in index.get("shards", []):
        if not isinstance(s, dict) or s.get("provenance") != ORIGINE_EXTERNE:
            continue
        base = Path(str(s.get("shard"))).name.split("__", 1)[-1]
        out[nom_sans_extension(base)] = out.get(nom_sans_extension(base), 0) + int(s.get("deposes") or 0)
    return out


def purger_rubans_de_transit(root: Path) -> dict[str, Any]:
    """Supprime un ruban externe de transit SEULEMENT si le coffre en détient toutes les lignes (index) et que le
    certificateur ne tourne pas. Le fichier source reste (original vérifié) ; le ruban se reconstruit à l'identique."""
    if (root / VERROU).exists():
        return {"statut": "REPORTE : le certificateur tourne", "supprimes": 0}
    scelles = rubans_scelles(_lire(root / INDEX) or {"shards": []})
    bilan: dict[str, Any] = {"statut": "FAIT", "supprimes": 0, "octets_liberes": 0, "gardes": {}}
    for chemin in sorted((root / HISTOIRE).glob("externe_*.jsonl.gz")):
        attendu = scelles.get(nom_sans_extension(chemin.name))
        if attendu is None:
            bilan["gardes"][chemin.name] = "pas encore au coffre"
            continue
        with gzip.open(chemin, "rb") as g:
            lignes = sum(1 for ligne in g if ligne.strip())
        if lignes != attendu:
            bilan["gardes"][chemin.name] = f"{lignes} lignes contre {attendu} au coffre"
            continue
        bilan["octets_liberes"] += chemin.stat().st_size
        chemin.unlink()
        bilan["supprimes"] += 1
    return bilan


def motif_deja_la(jeu: str, rec: dict, coffre: dict) -> str:
    """'' si la ligne peut entrer ; sinon le motif NOMMÉ. Retient la clé versée (aucun doublon entre fichiers)."""
    cles, debut = coffre["cles"], coffre["debut_alina"]
    if jeu == "liquidations":
        return "deja_au_coffre_alina" if (rec["coin"], rec.get("hash")) in cles["liquidations"] else ""
    if jeu in ("open-interest", "tardis-trades"):
        fam, t = ("asset_ctx", rec["ts_ms"]) if jeu == "open-interest" else ("trades_marche", rec["exchange_ts_ms"])
        return "apres_la_premiere_observation_alina" if debut.get(fam) is not None and t >= debut[fam] else ""
    k = (rec["coin"], (rec["ts_ms"] + H // 2) // H) if jeu == "funding" else (rec["coin"], rec["open_ts_ms"] // H)
    if k in cles[jeu]:
        return "deja_au_coffre_alina"
    cles[jeu].add(k)
    return ""


# --------------------------------------------------------------------------- versement

def nom_du_ruban(src: dict) -> str:
    tronc = JEUX[src["jeu"]][0]
    return f"{tronc}_{src['bornes'][1]:013d}{zlib.crc32((src['cle'] + '|' + src['version']).encode()):010d}.jsonl.gz"


def verser_un_fichier(root: Path, src: dict, admis: set[str], coffre: dict, etat: dict, depuis_ms: int,
                      now_ms: int) -> dict[str, Any]:
    jeu, (b0, b1) = src["jeu"], src["bornes"]
    famille = JEUX[jeu][1]
    nom = nom_du_ruban(src)
    detecte = detecter_famille(nom)
    if detecte is None or detecte[0] != famille:
        raise RuntimeError(f"le certificateur ne reconnaîtrait pas {nom} comme {famille} : {detecte}")
    final = root / HISTOIRE / nom
    if nom_sans_extension(nom) in coffre.get("rubans_scelles", {}):
        return {"fichier": src["cle"], "ruban": nom, "lus": 0, "ecrits": 0, "statut": "DEJA_AU_COFFRE"}
    # (début, fin, groupes admis à ce moment) : un groupe refusé hier reste candidat demain
    deja = [(int(x[0]), int(x[1]), set(x[2])) for x in etat.get(src["cle"], {}).get("intervalles", [])]
    bilan: dict[str, Any] = {"fichier": src["cle"], "ruban": nom, "lus": 0, "ecrits": 0}
    if final.exists():
        return {**bilan, "statut": "DEJA_VERSE"}
    if b1 < depuis_ms:
        return {**bilan, "statut": "AVANT_LA_PERIODE"}
    exclus: Counter = Counter()
    quar: Counter = Counter()
    base = {**PROVENANCE, "source": "TARDIS_FREE_DAY" if jeu == "tardis-trades" else "IRONFLOW_HF",
            "external_file": src["cle"]}
    coin_tardis = Path(src["cle"]).name.split(".")[0] if jeu == "tardis-trades" else ""
    lignes = lignes_tardis(src["chemin"]) if jeu == "tardis-trades" else lignes_ironflow(src["chemin"])
    part = final.with_name(nom + ".part")
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        with gzip.open(part, "wt", encoding="utf-8", newline="\n", compresslevel=6) as f:
            for r in lignes:
                bilan["lus"] += 1
                t = r["ts"]
                if not b0 <= t <= b1:
                    raise ValueError(f"horodatage {t} hors des bornes du manifeste [{b0} ; {b1}] : unité fausse ?")
                if t < depuis_ms:
                    exclus["avant_la_periode"] += 1
                    continue
                rec, motif = convertir(jeu, r, base, coin_tardis)
                if rec is None:
                    exclus[motif] += 1
                    continue
                groupe = rec["coin"] if jeu == "tardis-trades" else dex_de(rec["coin"])
                if any(a <= t <= b and groupe in g for a, b, g in deja):
                    exclus["deja_verse_version_precedente"] += 1
                    continue
                if groupe not in admis:
                    exclus["groupe_non_recoupe"] += 1
                    continue
                motif = motif_deja_la(jeu, rec, coffre)
                if motif:
                    exclus[motif] += 1
                    continue
                _, decision, raison = certifier_record(rec, famille=famille, source=detecte[1], now_ms=now_ms)
                if decision == QUARANTAINE:
                    quar[raison or "quarantaine"] += 1
                    continue
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
                bilan["ecrits"] += 1
        q = sum(quar.values())
        if q > QUARANTAINE_MAX * (q + bilan["ecrits"]):
            part.unlink()
            bilan["statut"] = f"REFUSE_QUARANTAINE ({q} sur {q + bilan['ecrits']})"
        elif bilan["ecrits"] == 0:
            part.unlink()
            bilan["statut"] = "RIEN_DE_NOUVEAU"
        else:
            _remplacer(part, final)
            bilan["statut"] = "VERSE"
    except BaseException:
        if part.exists():
            part.unlink()
        raise
    if not bilan["statut"].startswith("REFUSE"):
        # cet intervalle est traité : une nouvelle version du même fichier ne reverse que la suite
        e = etat.setdefault(src["cle"], {"intervalles": []})
        e["intervalles"].append([max(b0, depuis_ms), b1, sorted(admis)])
        e["version"] = src["version"]
    return {**bilan, "exclus": dict(exclus), "quarantaine": dict(quar)}


# --------------------------------------------------------------------------- scellement

def sceller(root: Path, rubans: list[str]) -> dict[str, dict]:
    """Le certificateur EXISTANT scelle les nouveaux rubans ; on relit ensuite SON manifeste."""
    if not rubans:
        return {}
    verrou_tenu = (root / VERROU).exists()
    t0 = time.time()
    cmd = [sys.executable, str(RACINE / "tools" / "sceller_coffre_local.py"), "--root", str(root)]
    for n in rubans:
        cmd += ["--nom", n]
    code = subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False).returncode
    vus: dict[str, dict] = {}
    dossier = root / MANIFESTES
    for m in sorted(dossier.glob("*.json")) if dossier.is_dir() else ():
        if m.stat().st_mtime + 1 < t0:
            continue
        for e in (_lire(m) or {}).get("fichiers", []):
            nom = Path(str(e.get("source", "")).replace("\\", "/")).name
            if nom in rubans:
                st = e.get("stats") or {}
                vus[nom] = {"statut": "SCELLE", "deposes": e.get("deposes"), "doublons": st.get("doublons"),
                            "quarantaine": st.get("quarantaine"), "shard": e.get("shard")}
    for n in rubans:
        if n not in vus:
            vus[n] = {"statut": ("EN_ATTENTE : le certificateur déjà en cours le scellera à son passage"
                                 if verrou_tenu else f"ECHEC : non scellé (code {code})")}
    return vus


# --------------------------------------------------------------------------- récolte

def premiers_du_mois(debut: str, fin: dt.date) -> list[str]:
    a, m = int(debut[:4]), int(debut[5:7])
    jours = []
    while dt.date(a, m, 1) <= fin:
        jours.append(f"{a:04d}-{m:02d}-01")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return jours


def recolter(root: Path) -> dict[str, Any]:
    import ingerer_ironflow
    import ingerer_tardis_jours_gratuits as tardis

    codes: dict[str, Any] = {}
    print("ETAPE 1/4 - Récolte Ironflow (incrémentale, empreintes SHA-256 vérifiées)", flush=True)
    try:
        codes["ironflow"] = ingerer_ironflow.main(["--racine", str(root)])
    except Exception as exc:  # noqa: BLE001 - la récolte informe ; on verse ce qui est déjà validé
        codes["ironflow"] = f"{type(exc).__name__}: {exc}"
    jours = premiers_du_mois("2026-05-01", dt.datetime.now(dt.timezone.utc).date())
    print(f"ETAPE 1/4 - Récolte Tardis : 1ers du mois {jours[0]} -> {jours[-1]}, {', '.join(COINS_TARDIS)}", flush=True)
    try:
        codes["tardis"] = tardis.main(["--racine", str(root), "--coins", *COINS_TARDIS, "--jours", *jours,
                                       "--max-mo", "3000"])
    except Exception as exc:  # noqa: BLE001
        codes["tardis"] = f"{type(exc).__name__}: {exc}"
    return codes


# --------------------------------------------------------------------------- plan (lecture seule)

def plan(root: Path, depuis_ms: int) -> int:
    sources = sources_validees(root)
    etat = _lire(root / ETAT) or {}
    print("PLAN - données externes -> coffre (lecture seule : aucun réseau, aucune écriture)")
    if not sources:
        print("  [!] aucun fichier validé : lancer sans --plan pour récolter.")
    par = Counter(s["jeu"] for s in sources)
    scelles = rubans_scelles(_lire(root / INDEX) or {"shards": []})
    for jeu, (_, fam) in JEUX.items():
        fait = sum(1 for s in sources if s["jeu"] == jeu and nom_sans_extension(nom_du_ruban(s)) in scelles)
        utiles = sum(1 for s in sources if s["jeu"] == jeu and s["bornes"][1] >= depuis_ms)
        print(f"  {jeu:<14} -> famille {fam:<16} {par[jeu]:>3} fichier(s) validé(s), {utiles:>3} dans la période, "
              f"{fait:>3} déjà au coffre")
    rec = _lire(root / RECOUPEMENT)
    print(f"  recoupement : {'dernier le ' + rec['genere_utc'] if rec else 'jamais fait (il se fera au lancement)'}")
    print("  certificateur du coffre : "
          + ("EN COURS (il scellera les rubans à son passage)" if (root / VERROU).exists() else "libre"))
    print(f"  fichiers source déjà traités : {len(etat)}")
    print("  jamais admis : carnet Tardis (aucune heure de réception par Alina) ; archive S3 Hyperliquid (payante)")
    return 0


# --------------------------------------------------------------------------- principal

def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--depuis", default=DEBUT_DEFAUT, help="premier jour versé au coffre (AAAA-MM-JJ)")
    p.add_argument("--plan", action="store_true", help="affiche l'état et le reste à faire, puis s'arrête")
    p.add_argument("--sans-telechargement", action="store_true")
    p.add_argument("--sans-scellement", action="store_true", help="verse les rubans sans lancer le certificateur")
    p.add_argument("--garder-rubans", action="store_true",
                   help="garde les rubans de transit même quand le coffre en détient toutes les lignes")
    p.add_argument("--now-ms", type=int, default=0, help="horloge injectable (tests)")
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    depuis_ms = ms_de(a.depuis)
    if a.plan:
        return plan(root, depuis_ms)
    now_ms = a.now_ms or int(time.time() * 1000)
    codes = {} if a.sans_telechargement else recolter(root)

    sources = sources_validees(root)
    if not sources:
        print("[REFUS] aucun fichier externe validé : rien ne peut entrer au coffre.", flush=True)
        return 2
    print("ETAPE 2/4 - Recoupement avec nos données, dex par dex (seuils fixés d'avance)", flush=True)
    recoupement = recouper(root, sources, depuis_ms)
    _ecrire_atomique(root / RECOUPEMENT, {"genere_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                          "depuis": a.depuis, "seuils": SEUILS, "paires_min": PAIRES_MIN,
                                          "resultats": recoupement})
    admis = groupes_admis(recoupement)
    for jeu, r in recoupement.items():
        refuses = sorted(g or "(natif)" for g, v in r.items() if not g.startswith("_") and not v.get("admis"))
        print(f"  {jeu:<14} admis : {sorted(g or '(natif)' for g in admis[jeu]) or 'AUCUN'}"
              + (f" | refusés : {refuses}" if refuses else "") + (f" | {r['_statut']}" if "_statut" in r else ""),
              flush=True)

    print(f"ETAPE 3/4 - Versement (depuis {a.depuis}) là où le coffre n'a rien d'Alina", flush=True)
    coffre = deja_au_coffre(root, depuis_ms)
    etat = _lire(root / ETAT) or {}
    bilans = []
    for src in sources:
        b = verser_un_fichier(root, src, admis.get(src["jeu"], set()), coffre, etat, depuis_ms, now_ms)
        bilans.append(b)
        _ecrire_atomique(root / ETAT, etat)                       # l'état suit chaque fichier : reprise exacte
        if b["statut"] not in ("DEJA_VERSE", "DEJA_AU_COFFRE", "AVANT_LA_PERIODE"):
            print(f"  {b['statut']:<16} {b['ecrits']:>10,} lignes  {src['cle']:<44} exclues : {b.get('exclus')}",
                  flush=True)
    # à sceller : tout ruban externe présent que le coffre ne détient pas encore -- y compris un ruban versé lors
    # d'un passage interrompu avant son scellement (23/11 : 5 rubans d'OI l'auraient sinon attendu indéfiniment)
    deja = rubans_scelles(_lire(root / INDEX) or {"shards": []})
    nouveaux = sorted(p.name for p in (root / HISTOIRE).glob("externe_*.jsonl.gz")
                      if nom_sans_extension(p.name) not in deja)

    scelles: dict[str, dict] = {}
    if a.sans_scellement:
        print("ETAPE 4/4 - scellement non demandé (--sans-scellement)", flush=True)
    else:
        print(f"ETAPE 4/4 - Mise au coffre de {len(nouveaux)} ruban(s) par le certificateur", flush=True)
        scelles = sceller(root, nouveaux)
    echecs = [n for n, v in scelles.items() if str(v["statut"]).startswith("ECHEC")]
    refuses = [b["ruban"] for b in bilans if b["statut"].startswith("REFUSE")]
    purge = {"statut": "non demandée"} if a.garder_rubans else purger_rubans_de_transit(root)
    _ecrire_atomique(root / RAPPORT, {
        "schema": "hypersmart.coffre_externe.v2",
        "genere_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "depuis": a.depuis,
        "recolte": codes, "groupes_admis": {k: sorted(v) for k, v in admis.items()}, "versements": bilans,
        "scellement": scelles, "purge_des_rubans_de_transit": purge, "provenance": PROVENANCE,
        "non_verifie": "la VALEUR de l'open interest n'est recoupée avec rien (seuls l'heure et le prix le sont)",
        "jamais_admis": {"carnet Tardis": "aucune heure de réception par Alina (received_at_ms) : jamais fabriquée",
                         "archive S3 Hyperliquid": "payante (403 en anonyme)"}})
    deposes = sum(int(v.get("deposes") or 0) for v in scelles.values())
    verse = sum(b["ecrits"] for b in bilans if b["statut"] == "VERSE")
    print(f"FIN - versé : {verse:,} lignes dans {len(nouveaux)} ruban(s) ; au coffre : {deposes:,} ; "
          f"fichiers refusés : {len(refuses)} ; échecs : {len(echecs)} ; rubans de transit supprimés : "
          f"{purge.get('supprimes', 0)} ({purge.get('octets_liberes', 0) / 1e6:.0f} Mo)", flush=True)
    return 1 if (echecs or refuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
