"""Étape 3/3 — campagne ALPHA-5 sur tape RÉELLE (lecture seule, 0 réseau, 0 ordre).

Fait tourner `cross_venue_conditions` (ALPHA-5) sur `runtime/data/bbo_synchro.jsonl` : chocs de prix
Binance, markout HL net des coûts HL, conditionné par les régimes causaux, avec embargo et comptage de
**tous** les essais au registre global.

Limite de données, dite avant tout chiffre : `bbo_synchro` porte les BBO synchronisés des deux venues,
**pas les aggTrades**. Les familles `AGG_IMBALANCE` et `TAKER_BURST` ne sont donc **pas mesurables** ici, et
les conditions d'OFI / profondeur non plus (elles exigent le carnet L2). Ces essais restent déclarés au
registre et ressortent `SHADOW_DONNEES_INSUFFISANTES` — ils ne sont ni supprimés ni comptés comme des échecs
de la stratégie : ils sont comptés comme non mesurés.

Aucune promotion n'est possible depuis ce module : le verdict plafonne à `DISCOVERY_PROBE`.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from hl_observer.experimental import cross_venue_conditions as CVC
from hl_observer.experimental import registre_essais
from hl_observer.experimental.cross_venue_events import detecter_chocs, mesurer_choc

SCHEMA_VERSION = "hypersmart.campagne_alpha5.v1"
SOURCE_RELPATH = Path("runtime") / "data" / "bbo_synchro.jsonl"
RAPPORT_RELPATH = Path("runtime") / "reports" / "campagne_alpha5.json"

#: Familles mesurables depuis une tape BBO seule. Les autres exigent les aggTrades.
FAMILLES_MESURABLES = ("PRICE_SHOCK",)
FAMILLES_NON_MESURABLES = ("AGG_IMBALANCE", "TAKER_BURST")

#: Paramètres PRÉ-ENREGISTRÉS (fixés avant lecture).
PARAMS = {"w_ms": 1_000.0, "seuil_bps": 8.0, "latence_ms": 400.0, "fee_ar_bps": 9.0,
          "slippage_bps": 1.0, "degradation_latence_bps": 1.0}
HORIZONS = (500, 1000, 2000)


def charger_tape(chemin: Path | str, coin: str, *, max_lignes: int = 300_000) -> dict[str, list]:
    """Rend `{binance_bt, hl_bbo, n_lignes}` pour un coin. Ligne illisible ou incomplète : ignorée."""
    bin_bt: list[tuple[int, float, float]] = []
    hl: list[tuple[int, float, float]] = []
    n = 0
    cible = str(coin).upper()
    try:
        with Path(chemin).open("r", encoding="utf-8", errors="replace") as fh:
            for i, ligne in enumerate(fh):
                if i >= max_lignes:
                    break
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    r = json.loads(ligne)
                except ValueError:
                    continue
                if not isinstance(r, dict) or str(r.get("coin") or "").upper() != cible:
                    continue
                n += 1
                ts = r.get("ts_ms")
                if not isinstance(ts, (int, float)):
                    continue
                try:
                    bb, ba = float(r["bin_bid"]), float(r["bin_ask"])
                    hb, ha = float(r["hl_bid"]), float(r["hl_ask"])
                except (KeyError, TypeError, ValueError):
                    continue
                if min(bb, ba, hb, ha) <= 0 or bb > ba or hb > ha:
                    continue
                bin_bt.append((int(ts), bb, ba))
                hl.append((int(ts), hb, ha))
    except OSError:
        return {"binance_bt": [], "hl_bbo": [], "n_lignes": 0}
    return {"binance_bt": bin_bt, "hl_bbo": hl, "n_lignes": n}


def _serie_hl(hl_bbo: list[tuple[int, float, float]]):
    s = sorted(hl_bbo, key=lambda x: x[0])
    return ([t for t, _, _ in s], [0.5 * (b + a) for _, b, a in s],
            [b for _, b, _ in s], [a for _, _, a in s])


def _contextes(mesures: list[dict], hl_bbo: list[tuple[int, float, float]]) -> dict[int, dict]:
    """Contexte causal par choc : mid HL avant/après. Le carnet L2 étant absent, OFI et profondeur
    restent volontairement non fournis ⇒ conditions `None` ⇒ jamais retenues."""
    temps, mids, _, _ = _serie_hl(hl_bbo)
    ctx: dict[int, dict] = {}
    for m in mesures:
        t = m.get("t_choc")
        if t is None:
            continue
        i_apres = next((i for i, x in enumerate(temps) if x >= t), None)
        if i_apres is None or i_apres == 0:
            continue
        ctx[t] = {"mid_avant": mids[i_apres - 1], "mid_apres": mids[i_apres]}
    return ctx


def executer(root: Path | str, *, coin: str = "BTC", max_lignes: int = 300_000,
             horizons: Iterable[int] = HORIZONS) -> dict[str, Any]:
    racine = Path(root)
    tape = charger_tape(racine / SOURCE_RELPATH, coin, max_lignes=max_lignes)
    rapport: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "coin": str(coin).upper(),
        "params_preenregistres": dict(PARAMS),
        "horizons_ms": list(horizons),
        "familles_mesurables": list(FAMILLES_MESURABLES),
        "familles_non_mesurables": list(FAMILLES_NON_MESURABLES),
        "limite_donnees": "bbo_synchro ne porte pas les aggTrades ni le carnet L2 : "
                          "AGG_IMBALANCE, TAKER_BURST, OFI et profondeur ne sont pas mesurables ici",
        "n_lignes_coin": tape["n_lignes"], "n_quotes": len(tape["hl_bbo"]),
        "shadow": True, "promotion_possible": False, "real_execution": False,
    }
    if len(tape["hl_bbo"]) < 50:
        return {**rapport, "statut": "DONNEES_INSUFFISANTES",
                "raison": "%d quotes exploitables pour %s" % (len(tape["hl_bbo"]), coin)}

    chocs = [c for c in detecter_chocs(tape["binance_bt"], [], w_ms=PARAMS["w_ms"],
                                       seuil_bps=PARAMS["seuil_bps"], seuil_imb_usd=float("inf"),
                                       seuil_burst_usd=float("inf"))
             if c["famille"] in FAMILLES_MESURABLES]
    hl = _serie_hl(tape["hl_bbo"])
    mesures = [mesurer_choc(c, hl, latence_ms=PARAMS["latence_ms"], horizons=tuple(horizons),
                            fee_ar_bps=PARAMS["fee_ar_bps"], slippage_bps=PARAMS["slippage_bps"],
                            degradation_latence_bps=PARAMS["degradation_latence_bps"])
               for c in chocs]
    mesurables = [m for m in mesures if m.get("statut") == "OK"]
    rapport.update({"n_chocs": len(chocs), "n_mesurables": len(mesurables)})

    enrichies = CVC.conditionner(mesurables, _contextes(mesurables, tape["hl_bbo"]))

    # pré-registration de TOUS les essais AVANT de lire un seul résultat
    plan = CVC.plan_essais(familles=FAMILLES_MESURABLES, horizons=tuple(horizons),
                           data_cutoff=rapport["genere_le"], univers="HL_BINANCE_%s" % coin.upper())
    CVC.enregistrer_plan(racine, plan)

    essais = registre_essais.charger(racine)
    sharpes = registre_essais.sharpes_tous_essais(essais, family=CVC.FAMILLE_REGISTRE)

    resultats: list[dict[str, Any]] = []
    verdicts: dict[str, Any] = {}
    for essai in plan:
        condition = str(essai["params"]["condition"])
        horizon = int(essai["horizon"])
        lot = CVC.filtrer_par_condition(enrichies, condition)
        v = CVC.verdict_conditionne(lot, horizon, sharpes_essais=sharpes, min_chocs=20)
        verdicts["%s|%dms" % (condition, horizon)] = {
            "statut": v["statut"], "n_mesurables": v["n_mesurables"],
            "pnl_net_bps": v.get("pnl_net_bps"), "sharpe": v.get("sharpe")}
        resultats.append({**essai, "result": v["statut"], "sharpe": v.get("sharpe"),
                          "pass_kill": "PASS" if v["statut"] == "DISCOVERY_PROBE" else "KILL"})
    CVC.enregistrer_resultats(racine, resultats)

    par_statut: dict[str, int] = {}
    for v in verdicts.values():
        par_statut[v["statut"]] = par_statut.get(v["statut"], 0) + 1
    probes = sorted(((k, v) for k, v in verdicts.items() if v["statut"] == "DISCOVERY_PROBE"),
                    key=lambda kv: -(kv[1]["pnl_net_bps"] or 0.0))
    return {**rapport, "statut": "EXECUTEE", "n_essais": len(plan),
            "verdicts_par_statut": par_statut, "probes": probes[:5], "verdicts": verdicts}


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Campagne ALPHA-5 sur tape reelle (lecture seule, shadow).")
    p.add_argument("--root", default=".")
    p.add_argument("--coin", default="BTC")
    p.add_argument("--max-lignes", type=int, default=300_000)
    a = p.parse_args(list(argv) if argv is not None else None)
    racine = Path(a.root).resolve()
    rapport = executer(racine, coin=a.coin, max_lignes=int(a.max_lignes))
    chemin = racine / RAPPORT_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print("%s | quotes=%s chocs=%s mesurables=%s essais=%s" % (
        rapport.get("statut"), rapport.get("n_quotes"), rapport.get("n_chocs"),
        rapport.get("n_mesurables"), rapport.get("n_essais")))
    print("statuts:", rapport.get("verdicts_par_statut"))
    for cle, v in (rapport.get("probes") or []):
        print("  PROBE %-34s n=%-4s net=%s bps" % (cle, v["n_mesurables"], v["pnl_net_bps"]))
    print("rapport:", chemin)
    return 0


__all__ = ["SCHEMA_VERSION", "PARAMS", "HORIZONS", "FAMILLES_MESURABLES", "FAMILLES_NON_MESURABLES",
           "charger_tape", "executer", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
