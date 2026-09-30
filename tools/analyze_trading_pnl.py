#!/usr/bin/env python3
"""AUDIT FORENSIQUE DU PnL — reconstruction complete, moteur par moteur.

LECTURE SEULE. N'ecrit QUE dans data/reports/ et docs/research/. Ne touche ni au serveur, ni au
ledger, ni a la configuration. Aucun ordre, jamais.

Ce que l'outil fait (pistes 1 a 12 du backlog) :
  * relit le ledger REEL (etat de session + archives), sans passer par le dashboard ;
  * reconstruit chaque aller-retour : entree -> sortie, avec sa duree ;
  * RECALCULE le PnL depuis les prix et les tailles, independamment du chiffre stocke ;
  * decompose : PnL brut, frais, funding, et ce qui reste inexplique ;
  * attribue chaque trade a un moteur (GRINDER / SNIPER / UNKNOWN_LEGACY) ;
  * produit deux courbes de PnL separees et les statistiques de chaque moteur ;
  * signale les anomalies comptables (doublons, orphelins, incoherences de signe).

Usage :
    python tools/analyze_trading_pnl.py
    python tools/analyze_trading_pnl.py --state runtime/data/ui_simulation_state.json
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.strategies.strategy_mode import (  # noqa: E402
    GRINDER,
    SNIPER,
    UNKNOWN_LEGACY,
    classify_event,
)

REPORTS = ROOT / "data" / "reports"
RESEARCH = ROOT / "docs" / "research"


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except (TypeError, ValueError):
        return d


def load_events(state_path: Path) -> tuple[list[dict], dict]:
    """Relit le ledger, MEME s'il est en cours d'ecriture par le serveur live.

    Le serveur reecrit ce fichier en continu : une lecture naive tombe sur un JSON tronque.
    Plutot que d'attendre ou de tuer le serveur (piste 1 : ne rien casser), on decode le tableau
    d'evenements OBJET PAR OBJET et on s'arrete proprement au premier objet incomplet.
    Aucun evenement n'est invente ; on lit ce qui est reellement ecrit, et rien de plus.
    """
    raw = state_path.read_text(encoding="utf-8", errors="ignore")

    # 1) tentative normale (fichier au repos)
    try:
        data = json.loads(raw)
        return [e for e in (data.get("simulation_ledger_events") or []) if isinstance(e, dict)], data
    except json.JSONDecodeError:
        pass

    # 2) fichier en cours d'ecriture : decodage incremental du tableau d'evenements
    marker = '"simulation_ledger_events"'
    i = raw.find(marker)
    if i < 0:
        raise SystemExit(f"ledger illisible et sans evenements : {state_path}")
    j = raw.find("[", i)
    if j < 0:
        raise SystemExit(f"tableau d'evenements introuvable : {state_path}")

    dec = json.JSONDecoder()
    events: list[dict] = []
    k = j + 1
    while True:
        while k < len(raw) and raw[k] in " \t\r\n,":
            k += 1
        if k >= len(raw) or raw[k] == "]":
            break
        try:
            obj, k = dec.raw_decode(raw, k)
        except json.JSONDecodeError:
            break                      # objet tronque : on s'arrete ici, sans rien inventer
        if isinstance(obj, dict):
            events.append(obj)

    print(f"  [lecture tolerante] fichier en cours d'ecriture : {len(events)} evenements complets lus")
    return events, {}


def collect_funding_arb(events: list[dict]) -> dict:
    """ANGLE MORT CORRIGE (2026-07-11) -- le Grinder n'ecrit PAS des OPEN/CLOSE.

    Le funding-arb (la seule strategie reellement "grinder" cablee) ecrit des actions
    `FUNDING_ARB_OPEN` / `FUNDING_ARB_ACCRUAL` / `FUNDING_ARB_CLOSE`. La premiere version de cet
    outil ne pairait que "OPEN"/"CLOSE" : elle n'aurait JAMAIS vu un trade Grinder, meme s'il y en
    avait eu. Conclure "0 trade Grinder" avec un outil aveugle au Grinder n'est pas une mesure.
    """
    out = {"open": 0, "accrual": 0, "close": 0, "funding_encaisse_usdc": 0.0,
           "couts_usdc": 0.0, "pnl_net_usdc": 0.0}
    for e in events:
        action = str(e.get("paper_action_type") or "").upper()
        if not action.startswith("FUNDING_ARB_"):
            continue
        kind = action.replace("FUNDING_ARB_", "").lower()
        if kind not in out:
            continue
        out[kind] += 1
        pnl = _f(e.get("estimated_net_pnl_usdc"))
        out["pnl_net_usdc"] += pnl
        if kind == "accrual":
            out["funding_encaisse_usdc"] += pnl
        else:
            out["couts_usdc"] += _f(e.get("fee_cost_usdc"))
    for k in ("funding_encaisse_usdc", "couts_usdc", "pnl_net_usdc"):
        out[k] = round(out[k], 6)
    return out


def build_round_trips(events: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Apparie chaque sortie a son entree. Retourne (trades, anomalies, positions_ouvertes)."""
    opens: dict[str, dict] = {}
    trades: list[dict] = []
    anomalies: list[dict] = []
    ouvertes: list[dict] = []          # positions encore ouvertes -- etat NORMAL, pas une anomalie
    seen_keys: set[str] = set()

    for e in events:
        action = str(e.get("paper_action_type") or "").upper()
        key = str(e.get("matched_position_key") or e.get("delta_key") or "")

        if action == "OPEN":
            dk = str(e.get("delta_key") or "")
            if dk and dk in seen_keys:
                anomalies.append({"type": "ENTREE_DUPLIQUEE", "delta_key": dk, "coin": e.get("coin")})
                continue
            if dk:
                seen_keys.add(dk)
            pk = f"{e.get('wallet_address')}|{e.get('coin')}|{e.get('leader_side')}"
            opens[pk] = e

        elif action == "CLOSE":
            pk = str(e.get("matched_position_key") or "")
            entry = opens.pop(pk, None)
            if entry is None:
                anomalies.append({"type": "FERMETURE_ORPHELINE", "coin": e.get("coin"),
                                  "position_key": pk})
                continue
            trades.append(_reconstruct(entry, e))

    # FAUSSE ANOMALIE CORRIGEE (2026-07-11). Une entree sans sortie n'est PAS un bug quand le
    # serveur TOURNE : c'est une position ENCORE OUVERTE. Crier a l'anomalie sur un etat normal,
    # c'est du bruit qui noie les vraies anomalies -- et ca fait douter d'un ledger qui va bien.
    # On les rapporte donc pour ce qu'elles sont : des positions ouvertes, pas des orphelines.
    for pk, e in opens.items():
        ouvertes.append({"coin": e.get("coin"), "side": e.get("leader_side"), "position_key": pk,
                         "strategy_mode": classify_event(e),
                         "notional_usdt": _f(e.get("copied_notional_usdt")),
                         "entry_price": _f(e.get("entry_price"))})

    return trades, anomalies, ouvertes


def _reconstruct(entry: dict, exit_: dict) -> dict:
    """Recalcule TOUT depuis les prix et les tailles -- sans faire confiance au PnL stocke."""
    coin = str(exit_.get("coin") or entry.get("coin") or "?")
    side = str(exit_.get("leader_side") or entry.get("leader_side") or "?").upper()
    ep = _f(exit_.get("average_entry_price") or entry.get("entry_price"))
    xp = _f(exit_.get("exit_price"))
    notional = _f(exit_.get("notional_closed_usdt") or entry.get("copied_notional_usdt"), 500.0)

    # --- PnL RECALCULE depuis la TAILLE et les PRIX, sans faire confiance au champ stocke.
    # `notional_closed_usdt` = taille x prix de SORTIE. Le PnL, lui, vaut taille x (prix_e - prix_s).
    # Utiliser le notionnel de SORTIE comme base introduit un biais de exit/entry -- c'est l'erreur
    # que faisait une premiere version de cet outil.
    size = (notional / xp) if xp > 0 else 0.0
    move_bps = ((xp - ep) / ep * 10_000.0) if ep > 0 else 0.0
    signed_bps = move_bps if side == "LONG" else -move_bps
    gross_recalc = size * ((xp - ep) if side == "LONG" else (ep - xp))

    # ------------------------------------------------------------------ FRAIS : NE PAS DOUBLER
    # ERREUR CORRIGEE (2026-07-11) -- j'avais ecrit ici `net = gross - (fee_in + fee_out)`, et
    # conclu a un "bug comptable : les frais d'entree ne sont deduits nulle part". C'ETAIT FAUX.
    #
    # Le prix d'entree stocke EST le prix de fill : `paper_engine.py` pose
    # `entry_price = exec_result.fill_price` et le declare explicitement
    # (`embedded_cost_model: "fill_price_includes_spread_slippage_fee_latency"`).
    # Le cout d'entree est donc DEJA dans le prix -- il degrade le `gross`. Le champ
    # `fee_cost_usdc` de l'evenement OPEN n'est qu'un REPORT de ce cout, pas une seconde ponction
    # (le bot ne debite pas `realized` a l'ouverture : cf. fusion_persistent_adapter, et
    # status_routes qui passe deja `fees_paid_usdc=0.0` "to avoid subtracting them twice").
    #
    # Le soustraire une seconde fois PESSIMISAIT le PnL de 0,50 $ sur 10 trades. Noircir un PnL
    # est aussi malhonnete que le flatter.
    fee_in = _f(entry.get("fee_cost_usdc"))          # deja DANS `entry_price` -- pour information
    fee_out = _f(exit_.get("fee_cost_usdc"))         # preleve a la sortie -- a soustraire, lui
    fees = fee_in + fee_out                          # cout TOTAL reel du round-trip (reporting)
    funding = exit_.get("funding_cost_usdc")
    funding_v = _f(funding) if funding is not None else 0.0
    net_recalc = gross_recalc - fee_out - funding_v

    gross_stored = _f(exit_.get("gross_pnl_usdc"))
    net_stored = _f(exit_.get("estimated_net_pnl_usdc"))

    opened = int(_f(exit_.get("opened_at_ms") or entry.get("observed_at_ms")))
    closed = int(_f(exit_.get("observed_at_ms")))
    duree_s = max(0.0, (closed - opened) / 1000.0)

    mode = classify_event(entry)
    if mode == UNKNOWN_LEGACY:
        mode = classify_event(exit_)

    return {
        "strategy_mode": mode,
        "coin": coin,
        "side": side,
        "notional_usdt": round(notional, 2),
        "entry_price": ep,
        "exit_price": xp,
        "move_bps": round(signed_bps, 2),
        "exit_method": str(exit_.get("exit_method") or exit_.get("reason") or "?"),
        "duration_s": round(duree_s, 1),
        "duration_h": round(duree_s / 3600.0, 3),
        "fees_usdc": round(fees, 4),
        "fee_entree_usdc": round(fee_in, 4),
        "fee_sortie_usdc": round(fee_out, 4),
        "funding_usdc": round(funding_v, 4) if funding is not None else None,
        "gross_pnl_recalc": round(gross_recalc, 4),
        "gross_pnl_stored": round(gross_stored, 4),
        "net_pnl_recalc": round(net_recalc, 4),
        "net_pnl_stored": round(net_stored, 4),
        "ecart_recalc_vs_stored": round(net_recalc - net_stored, 4),
        "signal_age_ms": entry.get("signal_age_ms"),
        "edge_remaining_bps": entry.get("edge_remaining_bps"),
        "leader_wallet": entry.get("wallet_address"),
        "opened_at_ms": opened,
        "closed_at_ms": closed,
    }


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    nets = [t["net_pnl_stored"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {
        "n": len(trades),
        "pnl_net_usdc": round(sum(nets), 2),
        "pnl_brut_usdc": round(sum(t["gross_pnl_stored"] for t in trades), 2),
        "frais_usdc": round(sum(t["fees_usdc"] for t in trades), 2),
        "funding_usdc": round(sum(t["funding_usdc"] or 0.0 for t in trades), 2),
        "winrate_pct": round(100.0 * len(wins) / len(nets), 1),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "expectancy_usdc": round(sum(nets) / len(nets), 3),
        "mediane_usdc": round(st.median(nets), 3),
        "gain_moyen": round(st.mean(wins), 3) if wins else 0.0,
        "perte_moyenne": round(st.mean(losses), 3) if losses else 0.0,
        "duree_mediane_h": round(st.median([t["duration_h"] for t in trades]), 3),
        "frais_sur_brut_pct": (
            round(100.0 * sum(t["fees_usdc"] for t in trades) / abs(sum(t["gross_pnl_stored"] for t in trades)), 1)
            if sum(t["gross_pnl_stored"] for t in trades) else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="runtime/data/ui_simulation_state.json")
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    RESEARCH.mkdir(parents=True, exist_ok=True)

    events, _ = load_events(ROOT / args.state)
    trades, anomalies, ouvertes = build_round_trips(events)
    funding_arb = collect_funding_arb(events)

    par_mode: dict[str, list[dict]] = collections.defaultdict(list)
    for t in trades:
        par_mode[t["strategy_mode"]].append(t)

    forensics = {
        "evenements_lus": len(events),
        "aller_retours_reconstruits": len(trades),
        "anomalies": anomalies,
        "positions_encore_ouvertes": ouvertes,
        "funding_arb_grinder": funding_arb,
        "global": stats(trades),
        "par_moteur": {m: stats(v) for m, v in par_mode.items()},
        "reconciliation": {
            "ecart_max_recalc_vs_stored": round(
                max((abs(t["ecart_recalc_vs_stored"]) for t in trades), default=0.0), 6),
            "trades_incoherents": [
                {"coin": t["coin"], "ecart": t["ecart_recalc_vs_stored"]}
                for t in trades if abs(t["ecart_recalc_vs_stored"]) > 0.01
            ],
        },
    }

    (REPORTS / "pnl_forensics.json").write_text(
        json.dumps(forensics, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "trades_enriched.json").write_text(
        json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8")

    if trades:
        with (REPORTS / "trades_enriched.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(trades[0].keys()))
            w.writeheader()
            w.writerows(trades)

    with (REPORTS / "grinder_vs_sniper.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["moteur", "trades", "pnl_net", "pnl_brut", "frais", "funding",
                    "winrate_pct", "profit_factor", "expectancy", "duree_mediane_h"])
        for m in (GRINDER, SNIPER, UNKNOWN_LEGACY):
            s = stats(par_mode.get(m, []))
            if s["n"]:
                w.writerow([m, s["n"], s["pnl_net_usdc"], s["pnl_brut_usdc"], s["frais_usdc"],
                            s["funding_usdc"], s["winrate_pct"], s["profit_factor"],
                            s["expectancy_usdc"], s["duree_mediane_h"]])

    # ------- affichage
    print("=" * 78)
    print("  AUDIT FORENSIQUE DU PnL — reconstruit depuis le ledger, moteur par moteur")
    print("=" * 78)
    g = forensics["global"]
    print(f"\n  evenements lus            : {forensics['evenements_lus']}")
    print(f"  aller-retours reconstruits : {forensics['aller_retours_reconstruits']}")
    if g["n"]:
        print(f"  PnL net total             : {g['pnl_net_usdc']:+.2f} $")
    print(f"\n  RECONCILIATION (PnL recalcule vs PnL stocke)")
    print(f"    ecart maximum : {forensics['reconciliation']['ecart_max_recalc_vs_stored']:.6f} $", end="")
    print("   -> le PnL stocke est JUSTE" if forensics['reconciliation']['ecart_max_recalc_vs_stored'] < 0.01
          else "   <<< INCOHERENCE")

    print(f"\n  SEPARATION DES MOTEURS")
    print(f"  {'moteur':16s} {'n':>4s} {'PnL net':>10s} {'PnL brut':>10s} {'frais':>8s} "
          f"{'WR':>6s} {'PF':>6s} {'duree med':>10s}")
    for m in (GRINDER, SNIPER, UNKNOWN_LEGACY):
        s = stats(par_mode.get(m, []))
        if not s["n"]:
            continue
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "  inf"
        print(f"  {m:16s} {s['n']:4d} {s['pnl_net_usdc']:+10.2f} {s['pnl_brut_usdc']:+10.2f} "
              f"{s['frais_usdc']:8.2f} {s['winrate_pct']:5.0f}% {pf:>6s} {s['duree_mediane_h']:9.2f}h")

    if anomalies:
        c = collections.Counter(a["type"] for a in anomalies)
        print(f"\n  ANOMALIES COMPTABLES : {dict(c)}")
    else:
        print("\n  ANOMALIES COMPTABLES : aucune")

    if ouvertes:
        par_moteur = collections.Counter(o["strategy_mode"] for o in ouvertes)
        expo = sum(o["notional_usdt"] for o in ouvertes)
        print(f"  POSITIONS ENCORE OUVERTES : {len(ouvertes)} ({dict(par_moteur)}), "
              f"notionnel {expo:.0f} $ -- etat normal, ce ne sont pas des orphelines")

    print(f"\n  rapports ecrits dans data/reports/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
