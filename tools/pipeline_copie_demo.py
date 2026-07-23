"""PIPELINE COPY-VAULTS BOUT-EN-BOUT sur FIXTURE SYNTHÉTIQUE (rectif Flo 23/07).

⚠️ TEST_FIXTURE — CE N'EST PAS UNE PREUVE D'EDGE RÉEL. Le sandbox n'a pas le réseau HL ; ce script
génère des fills SYNTHÉTIQUES (avec un edge intégré exprès + un RETRAIT à exclure) et fait tourner TOUT
le pipeline réel — reconstruction d'épisodes, exclusion des retraits, mesure OOS train→walk-forward vs
placebo, simulation paper — pour PROUVER que la machinerie produit tous les chiffres demandés et pour
montrer la forme exacte du rapport. Les VRAIS chiffres viendront de `backfill_vault_fills.py` (réseau,
chez Flo) suivi de ce même pipeline sur les fills réels. On ne présente jamais ce fixture comme réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.experimental.copy_edge_oos import mesurer_oos, simuler_paper  # noqa: E402

H = 300_000            # horizon 5 min
NAV = 100_000.0
EDGE_FRAC = 0.004      # +40 bps intégré APRÈS chaque entrée alpha (edge synthétique à retrouver)


def fixture_fills() -> list[dict]:
    """Fills synthétiques : 60 entrées alpha long sur des coins UNIQUES (pas de dérive cumulée),
    + 1 RETRAIT pro-rata (3 coins avec position debout) qui DOIT être exclu de l'alpha."""
    fills = []
    t = 1_000_000_000_000
    for k in range(60):
        fills.append({"time": t, "coin": "E%02d" % k, "px": "100", "sz": "60", "side": "B",
                      "dir": "Open Long", "startPosition": "0"})       # OPEN long, coin unique
        t += 2 * H
    # RETRAIT : 3 coins ouverts (position debout), puis réduction pro-rata SIMULTANÉE (~20 %)
    for coin in ("WA", "WB", "WC"):
        fills.append({"time": 1_000_000_000_000 - H, "coin": coin, "px": "100", "sz": "10", "side": "B",
                      "dir": "Open Long", "startPosition": "0"})
    for coin in ("WA", "WB", "WC"):
        fills.append({"time": t + 1000, "coin": coin, "px": "100", "sz": "2", "side": "A",
                      "dir": "Close Long", "startPosition": "10"})     # reduce pro-rata = RETRAIT
    return VB.parser_fills(fills, vault="0xSYNTH")


def fixture_tape(entrees: list[dict]) -> dict:
    """Par coin, un PIC propre : plat à 100, +EDGE_FRAC pile à te+H, retour à 100 ensuite. Le forward
    te→te+H capture +EDGE ; un instant aléatoire (placebo) tombe surtout sur du plat → ≈ 0."""
    tape: dict[str, list[tuple[int, float]]] = {}
    for e in entrees:
        te, c = e["ts_ms"], e["coin"]
        pts = tape.setdefault(c, [])
        pts += [(te - H, 100.0), (te, 100.0), (te + H, 100.0 * (1.0 + EDGE_FRAC)), (te + 2 * H, 100.0)]
    for c in tape:
        tape[c] = sorted(set(tape[c]))
    return tape


def main() -> int:
    print("=" * 78)
    print("PIPELINE COPY-VAULTS — FIXTURE SYNTHÉTIQUE (TEST_FIXTURE, PAS un edge réel)")
    print("=" * 78)
    fills = VB.dedupliquer(fixture_fills())
    cov = VB.couverture(fills)
    episodes = VB.marquer_retraits(VB.reconstruire_episodes(fills))
    alpha = VB.entrees_alpha(episodes)
    for e in alpha:                                                   # attache move_frac (taille/NAV)
        e["move_frac"] = round(e["taille_usd"] / NAV, 4)
    retraits = [e for e in episodes if e.get("retrait_probable")]
    print("\n[1] ÉVÉNEMENTS RECONSTRUITS")
    print("    fills=%d | épisodes=%d | entrées alpha=%d | reduces de RETRAIT exclus=%d"
          % (len(fills), len(episodes), len(alpha), len(retraits)))
    print("    couverture: %.1f h, coins=%s" % (cov["span_h"], cov["coins"]))
    tape = fixture_tape(alpha)
    print("\n[2] MESURE OOS (choix sur TRAIN, validation walk-forward vs PLACEBO)")
    m = mesurer_oos(alpha, tape, seuils=(0.03, 0.05), horizons_ms=(H,), frais_bps=12.0,
                    min_events_train=10, min_events_oos=10, frac_train=0.6)
    print("    statut=%s | n_train=%s n_oos=%s" % (m["statut"], m.get("n_train"), m.get("n_oos")))
    if m["statut"] == "MESURE":
        ch, oos = m["choix_sur_train"], m["oos"]
        print("    choix TRAIN: seuil=%.0f%% horizon=%.0fmin train_net=%.1f bps"
              % (ch["seuil"] * 100, ch["horizon_ms"] / 60000, ch["train_net_bps"]))
        print("    OOS: brut=%.1f net=%.1f placebo=%.1f edge_vs_placebo=%.1f bps -> VALIDÉ=%s"
              % (oos["brut_bps"], oos["net_bps"], oos["placebo_bps"], oos["edge_vs_placebo_bps"], m["edge_valide_oos"]))
        print("\n[3] SIMULATION PAPER (période OOS, coûts inclus)")
        sim = simuler_paper([e for e in alpha], tape, horizon_ms=ch["horizon_ms"], seuil=ch["seuil"],
                            notional_usd=150.0, cout_ar_bps=12.0, capital_usd=1000.0)
        print("    trades=%d | PnL net=%.2f$ | ROI=%.2f%% | drawdown=%.2f%% | winrate=%.0f%% | PF=%s | capacité/trade=%.0f$"
              % (sim["n_trades"], sim["pnl_net_usd"], sim["roi_pct"], sim["drawdown_pct"],
                 sim["winrate_pct"], sim["profit_factor"], sim["capacite_usd_par_trade"]))
    print("\n⚠️  TEST_FIXTURE : chiffres synthétiques prouvant le PIPELINE, PAS un edge réel.")
    print("    Réel = backfill_vault_fills.py (réseau) -> mêmes étapes sur les vrais fills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
