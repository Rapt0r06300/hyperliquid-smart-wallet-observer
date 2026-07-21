"""CLI DES BACKTESTS — carry (scans enregistres) ET arbitrage (ecarts cross-venue).

Lecture seule sur `runtime/replay/carry_scan.jsonl`. N'ouvre rien, ne ferme rien, ne touche
jamais le PnL live (tout tourne en mode BACKTEST). Sans donnees, il le DIT et sort en 0 :
un backtest muet n'est pas un echec de la chaine de tests, c'est un journal encore jeune.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.arb_backtest import (balayer as arb_balayer,       # noqa: E402
                                                  charger_serie, convergence,
                                                  verdict as arb_verdict)
from hl_observer.backtesting.carry_backtest import balayer, verdict            # noqa: E402
from hl_observer.backtesting.carry_scan_recorder import charger, resume        # noqa: E402

SORTIE = Path("runtime") / "replay" / "BACKTEST_CARRY.md"
SORTIE_ARB = Path("runtime") / "replay" / "BACKTEST_ARBITRAGE.md"


def _md(res, v, inv) -> str:
    l = ["# Backtest carry — nos vraies passes, rejouees sous d'autres reglages", "",
         "_Genere le %s. Lecture seule, mode BACKTEST : ce PnL ne touche jamais le live._"
         % time.strftime("%d/%m/%Y %H:%M"), "",
         "## Donnees",
         "",
         "- **%d ligne(s)** de scan sur **%d passe(s)**, %.1f h, %d coin(s), %.2f Mo"
         % (inv["lignes"], inv["passes"], inv["etendue_h"], inv["coins"], inv["octets"] / 1e6),
         "- viables : %d ligne(s)" % inv["viables"], ""]
    if inv.get("motifs_de_refus"):
        l += ["- motifs de refus dominants :", ""]
        l += ["  - `%s` x%d" % (m, n) for m, n in inv["motifs_de_refus"].items()]
        l.append("")
    l += ["## Verdict", "", "**%s**" % v["conclusion"], ""]
    for cle in ("detail", "avertissement"):
        if v.get(cle):
            l += ["> " + str(v[cle]), ""]
    if v.get("gain_vs_actuel_pct") is not None:
        l += ["- gain du meilleur reglage vs la production : **%+.1f %%**"
              % v["gain_vs_actuel_pct"], ""]
    if res:
        l += ["## Classement (PnL paper decroissant)", "",
              "| reglage | PnL $ | $/jour | ouvertures | fermetures | renforts | positions |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        for r in res[:20]:
            l.append("| `%s` | %+.6f | %+.6f | %d | %d | %d | %d |"
                     % (r.config.nom(), r.pnl_total_usd, r.pnl_par_jour_usd, r.ouvertures,
                        r.fermetures, r.renforts, r.positions_finales))
        l.append("")
    l += ["---", "",
          "**Securite : 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · "
          "0 depot/retrait.**", ""]
    return "\n".join(l)


def _md_arb(conv, res, v) -> str:
    l = ["# Backtest arbitrage de dislocation — l'ecart se referme-t-il ?", "",
         "_Genere le %s. Lecture seule, mode BACKTEST._" % time.strftime("%d/%m/%Y %H:%M"), "",
         "## 1. La question prealable : CONVERGENCE", "",
         "> Baisser un seuil augmente le nombre de trades — ca ne cree pas d'edge. La seule",
         "> question qui compte d'abord : un ecart HL <-> Binance se referme-t-il ?", "",
         "- %d observation(s) d'ecart sur %d coin(s), seuil d'etude %.1f bps"
         % (conv.get("observations", 0), conv.get("coins", 0), conv.get("seuil_bps", 0.0)), ""]
    if conv.get("horizons"):
        l += ["| horizon | paires | variation moyenne de \\|ecart\\| | part reduite |",
              "|---|---:|---:|---:|"]
        for h, d in conv["horizons"].items():
            if not d.get("n"):
                l.append("| %s | 0 | — | — |" % h)
            else:
                l.append("| %s | %d | **%+.3f bps** | %.1f %% |"
                         % (h, d["n"], d["delta_moyen_bps"], d["part_reduite_pct"]))
        l.append("")
    if conv.get("verdict"):
        l += ["**%s**" % conv["verdict"], ""]
    l += ["## 2. Balayage des seuils (seulement si (1) le permet)", ""]
    if res:
        l += ["| reglage | entrees | winrate | PnL $ | capture moy. | duree moy. | sorties age |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        for r in res[:15]:
            d = r.resume()
            l.append("| `%s` | %d | %s | %+.6f | %.2f bps | %.2f h | %d |"
                     % (d["config"], d["entrees"],
                        ("%.0f %%" % d["winrate_pct"]) if d["winrate_pct"] is not None else "—",
                        d["pnl_usd"], d["capture_moyenne_bps"], d["duree_moyenne_h"],
                        d["sorties_par_age"]))
        l.append("")
    l += ["## Verdict", "", "**%s**" % v["conclusion"], ""]
    for cle in ("detail", "avertissement"):
        if v.get(cle):
            l += ["> " + str(v[cle]), ""]
    l += ["---", "",
          "**Securite : 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · "
          "0 depot/retrait.**", ""]
    return "\n".join(l)


def _ecrire(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(texte, encoding="utf-8")
    os.replace(tmp, chemin)                      # atomique : jamais un rapport tronque


def main(argv: list[str] | None = None) -> int:
    root = Path((argv or sys.argv[1:] or ["."])[0])
    inv = resume(root)
    lignes = charger(root)
    res = balayer(lignes) if lignes else []
    v = verdict(res)
    chemin = root / SORTIE
    _ecrire(chemin, _md(res, v, inv))

    print("  journal de scans : %d ligne(s), %d passe(s), %.1f h, %d coin(s)"
          % (inv["lignes"], inv["passes"], inv["etendue_h"], inv["coins"]))
    print("  verdict : %s" % v["conclusion"])
    if v.get("detail"):
        print("    %s" % str(v["detail"])[:220])
    if v.get("gain_vs_actuel_pct") is not None:
        print("    gain du meilleur reglage vs production : %+.1f %%" % v["gain_vs_actuel_pct"])
    print("  rapport : %s" % chemin)

    # ── ARBITRAGE : la convergence D'ABORD, le balayage de seuils ensuite.
    serie = charger_serie(root)
    conv = convergence(serie, seuil_bps=8.0)
    res_arb = arb_balayer(serie) if serie else []
    v_arb = arb_verdict(conv, res_arb)
    _ecrire(root / SORTIE_ARB, _md_arb(conv, res_arb, v_arb))
    print("  arbitrage : %d ecart(s) sur %d coin(s)"
          % (conv.get("observations", 0), conv.get("coins", 0)))
    if conv.get("verdict"):
        print("    convergence : %s" % str(conv["verdict"])[:180])
    print("    verdict : %s" % v_arb["conclusion"])
    if v_arb.get("meilleur"):
        m = v_arb["meilleur"]
        print("    meilleur reglage : %s -> %d entrees, PnL %+.4f $, capture %.2f bps"
              % (m["config"], m["entrees"], m["pnl_usd"], m["capture_moyenne_bps"]))
    print("  rapport : %s" % (root / SORTIE_ARB))
    return 0                                     # jamais bloquant : un journal jeune n'est pas un echec


if __name__ == "__main__":
    raise SystemExit(main())
