"""PIPELINE COPY-VAULTS BOUT-EN-BOUT sur FIXTURE SYNTHÉTIQUE (rectif Flo 23/07).

⚠️ TEST_FIXTURE — CE N'EST PAS UNE PREUVE D'EDGE RÉEL. Le sandbox n'a pas le réseau HL ; ce script
génère des fills SYNTHÉTIQUES (edge intégré exprès + un RETRAIT à exclure, plusieurs vaults) et fait
tourner TOUT le pipeline réel — épisodes, exclusion des retraits, mesure OOS PURGÉE par période ET par
vault vs placebo avec IC, simulation paper (ROI cumulé ET par trade), ranking de variantes, décision
SCALE/KILL — pour PROUVER la machinerie et montrer la forme du rapport. Les VRAIS chiffres viennent de
`pipeline_copie_reel.py` (réseau, chez Flo). On ne présente jamais ce fixture comme réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.experimental.copy_edge_oos import mesurer_oos, simuler_paper, ranger_variantes  # noqa: E402

H = 300_000
NAV = 100_000.0
EDGE_FRAC = 0.004      # +40 bps intégré APRÈS chaque entrée (edge synthétique à retrouver)
VAULTS = 6


def fixture_fills() -> list[dict]:
    """72 entrées long sur 6 vaults, coins UNIQUES ; + 1 RETRAIT pro-rata (3 coins) sur un vault."""
    fills, t = [], 1_000_000_000_000
    for k in range(72):
        fills.append({"time": t, "coin": "E%03d" % k, "px": "100", "sz": "60", "side": "B",
                      "dir": "Open Long", "startPosition": "0", "vault": "V%d" % (k % VAULTS)})
        t += H
    for coin in ("WA", "WB", "WC"):                                # position debout puis retrait pro-rata
        fills.append({"time": t - 2 * H, "coin": coin, "px": "100", "sz": "10", "side": "B",
                      "dir": "Open Long", "startPosition": "0", "vault": "V0"})
    for coin in ("WA", "WB", "WC"):
        fills.append({"time": t, "coin": coin, "px": "100", "sz": "2", "side": "A",
                      "dir": "Close Long", "startPosition": "10", "vault": "V0"})
    # parser_fills lit 'vault' par fill
    out = []
    for f in fills:
        out += VB.parser_fills([f], vault=f["vault"])
    return out


def fixture_tape(entrees):
    tape = {}
    for e in entrees:
        te, c = e["ts_ms"], e["coin"]
        tape[c] = [(te - H, 100.0), (te, 100.0), (te + H, 100.0 * (1 + EDGE_FRAC)), (te + 2 * H, 100.0)]
    return tape


def main() -> int:
    print("=" * 80)
    print("PIPELINE COPY-VAULTS — FIXTURE SYNTHÉTIQUE (TEST_FIXTURE, PAS un edge réel)")
    print("=" * 80)
    fills = VB.dedupliquer(fixture_fills())
    episodes = VB.marquer_retraits(VB.reconstruire_episodes(fills))
    alpha = VB.entrees_alpha(episodes)
    for e in alpha:
        e["move_frac"] = round(e["taille_usd"] / NAV, 4)
    retraits = [e for e in episodes if e.get("retrait_probable")]
    cov = VB.couverture(fills)
    print("\n[1] ÉVÉNEMENTS RECONSTRUITS")
    print("    fills=%d | épisodes=%d | entrées alpha=%d | reduces de RETRAIT exclus=%d | vaults=%d | %.1f h"
          % (len(fills), len(episodes), len(alpha), len(retraits), cov["n_vaults"], cov["span_h"]))
    tape = fixture_tape(alpha)
    print("\n[2] MESURE OOS — choix sur TRAIN, validation PURGÉE par période ET par vault, vs placebo + IC")
    m = mesurer_oos(alpha, tape, seuils=(0.03, 0.05), horizons_ms=(H,), frais_bps=12.0,
                    min_events_train=10, min_events_oos=10, seuil_validation=15, graine=1)
    print("    statut=%s | vaults_train=%s vaults_oos=%s | purge=%.0fmin"
          % (m["statut"], m["vaults_train"], m["vaults_oos"], m["purge_ms"] / 60000))
    o = m["oos"]
    print("    OOS (n=%d): net=%.1f bps | placebo=%.1f | edge_vs_placebo=%.1f | IC95=[%.1f, %.1f] bps"
          % (o["n"], o["net_bps"], o["placebo_bps"], o["edge_vs_placebo_bps"], o["ic95_bas_bps"], o["ic95_haut_bps"]))
    print("    edge_validé_OOS=%s -> DÉCISION=%s" % (m["edge_valide_oos"], m["decision"]))
    print("\n[3] SIMULATION PAPER (OOS, coûts inclus) — ROI cumulé ≠ ROI par trade")
    sim = simuler_paper(alpha, tape, horizon_ms=o["horizon_ms"], seuil=o["seuil"],
                        notional_usd=150.0, cout_ar_bps=12.0, capital_usd=1000.0)
    print("    trades=%d | PnL net=%.2f$ | ROI cumulé=%.2f%% (sur 1000$) | ROI/trade=%.1f bps [IC95 %s]"
          % (sim["n_trades"], sim["pnl_net_usd"], sim["roi_cumulatif_pct"], sim["roi_par_trade_bps"],
             sim["roi_par_trade_ic95_bps"]))
    print("    drawdown=%.2f%% | winrate=%.0f%% | profit_factor=%s | capacité/trade=%.0f$"
          % (sim["drawdown_pct"], sim["winrate_pct"], sim["profit_factor"], sim["capacite_usd_par_trade"]))
    print("\n[4] RANKING DES VARIANTES (score = PnL × ROI × capacité ÷ drawdown)")
    variantes = [{"seuil": s, "horizon_ms": H} for s in (0.03, 0.05, 0.10)]
    for r in ranger_variantes(alpha, tape, variantes=variantes)[:3]:
        print("    seuil=%.0f%% h=%.0fmin score=%.1f | PnL=%.2f$ ROI_cum=%.2f%% ROI/trade=%.1fbps DD=%.2f%%"
              % (r["seuil"] * 100, r["horizon_ms"] / 60000, r["score"], r["pnl_net_usd"],
                 r["roi_cumulatif_pct"], r["roi_par_trade_bps"], r["drawdown_pct"]))
    print("\n⚠️  TEST_FIXTURE : chiffres synthétiques prouvant le PIPELINE, PAS un edge réel.")
    print("    Réel = pipeline_copie_reel.py (réseau) -> mêmes étapes sur les vrais fills + candles + ledger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
