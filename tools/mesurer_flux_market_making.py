#!/usr/bin/env python3
"""ENREGISTRE LE FLUX REEL DES 10 CANDIDATS, PUIS REND LE VERDICT (2026-07-12).

Le carnet a donne 10 marches ou le market making SEMBLE possible. Il manque la seule chose qui
decide : y a-t-il QUELQU'UN EN FACE, et le prix nous punit-il apres nous avoir remplis ?

    python tools/mesurer_flux_market_making.py            # 30 min d'ecoute, puis verdict
    python tools/mesurer_flux_market_making.py --minutes 5
    python tools/mesurer_flux_market_making.py --verdict-seulement   # sur les donnees deja la

Process AUTONOME : il ne touche pas au serveur qui tourne.
Canal PUBLIC `trades`. LECTURE SEULE. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.market_making_flow import encadrer_le_market_making  # noqa: E402
from hl_observer.collection.trades_recorder import enregistrer  # noqa: E402

DOSSIER = str(ROOT / "runtime" / "replay")


def _carnet_par_coin() -> dict:
    """Toutes les statistiques de carnet, par coin. Aucun filtre : on TRIE plus tard."""
    from collections import defaultdict as dd

    par = dd(list)
    for f in sorted(ROOT.glob("runtime/replay/l2_book*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("coin") and r.get("spread_bps") is not None:
                    par[r["coin"]].append(r)

    out = {}
    for c, v in par.items():
        if len(v) < 3:
            continue
        out[c] = {
            "spread_bps": statistics.median([float(x["spread_bps"]) for x in v]),
            "bid_depth_usd": statistics.median([float(x.get("bid_depth_usd") or 0.0) for x in v]),
            "ask_depth_usd": statistics.median([float(x.get("ask_depth_usd") or 0.0) for x in v]),
            "n_releves": len(v),
        }
    return out


def univers_d_ecoute(carnet: dict, forces: list[str] | None = None) -> dict:
    """QUI ECOUTE-T-ON ? Le spread seul decide. La profondeur, elle, decide au VERDICT.

    LE BUG QUE CETTE FONCTION CORRIGE (2026-07-12)
    ----------------------------------------------
    L'univers d'ecoute reprenait les 4 filtres du carnet -- dont un plancher de profondeur de
    2 500 $ que J'AI choisi. Resultat : **KAITO, la piece que la tasklist demande justement de
    trancher, en etait EXCLU** (profondeur ask mediane 1 681 $ ... mesuree sur 8 releves).
    On serait parti ecouter 4 h un univers qui ne contenait pas le sujet de la question.

    LA REGLE, DEJA APPRISE AVEC LE CARNET L2 (2026-07-11) :
    **le deny-by-default protege les ORDRES, pas les OCTETS.** Ecouter un marche de plus ne
    coute rien et n'engage rien. Refuser de le TRADER, ca c'est un verdict -- et ca se prononce
    sur la donnee, pas avant de l'avoir.

    On ecoute donc tout ce dont le spread paie au moins les frais, plus tout marche force.
    """
    ecoute = {}
    for c, st in carnet.items():
        # seul critere : le demi-spread couvre-t-il le cout aller-retour maker (3 bps) ?
        if st["spread_bps"] * 0.5 > 3.0:
            ecoute[c] = st["spread_bps"]
    for c in forces or ():
        c = str(c).strip().upper()
        if not c:
            continue
        if c in carnet:
            ecoute[c] = carnet[c]["spread_bps"]
        elif c not in ecoute:
            # pas de carnet pour lui : on l'ecoute quand meme, le verdict dira "spread inconnu"
            ecoute[c] = float("nan")
    return ecoute


def _charger_trades() -> dict:
    par = defaultdict(list)
    for f in sorted(ROOT.glob("runtime/replay/trades*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if t.get("coin"):
                    par[t["coin"]].append(t)
    return par


def _verdict(spreads: dict, carnet: dict | None = None) -> int:
    """LE VERDICT T1 -- sans le nombre invente.

    On ne suppose plus "10 % du flux". On rend les TROIS bornes de file, et on tranche sur la
    seule qui nous concerne : DERRIERE (un retail sans colocation est derriere les MM pros).
    Le `net_bps` ne depend d'AUCUNE hypothese de file -- c'est lui qui decide du signe.

    ET, DEPUIS LE 2026-07-12, LE VERROU DE FILE PASSE EN PREMIER.
    La profondeur reellement posee devant nous vient du carnet L2. Un marche dont le flux ne
    balaye pas cette profondeur ne peut PAS etre declare CANDIDAT, si beau que soit son
    markout. C'est ce verrou qui a tue CASHCAT (0,19 % du flux) -- et c'est tant mieux : mieux
    vaut un candidat mort qu'un candidat imaginaire.
    """
    par_coin = _charger_trades()
    if not par_coin:
        print("\n  AUCUN trade enregistre. Lance d'abord l'ecoute (sans --verdict-seulement).\n")
        return 2

    print("\n  Position dans la file = DERRIERE (retail, sans colocation). On ne suppose RIEN :")
    print("  les 3 bornes sont calculees, et c'est la borne realiste qui tranche.\n")
    print("  %-10s %6s %7s  %9s  %-19s  %s"
          % ("coin", "fills", "spread", "adverse", "net bps [IC 90%]", "verdict"))
    print("  %-10s %6s %7s  %9s  %-19s  %s"
          % ("-" * 10, "-" * 6, "-" * 7, "-" * 9, "-" * 19, "-" * 34))

    verdicts = []
    for coin, trades in sorted(par_coin.items(), key=lambda kv: -len(kv[1])):
        sp = spreads.get(coin)
        if sp is None:
            continue
        if sp != sp:                      # NaN : force sans carnet -> on ne fabrique pas un spread
            print("  %-10s %6s %7s  %9s  %-19s  %s"
                  % (coin, "-", "-", "-", "-",
                     "SPREAD INCONNU (aucun carnet) -> aucun verdict"))
            continue

        # LA PROFONDEUR REELLEMENT POSEE DEVANT NOUS -> verrou de file (deny-by-default).
        # Sans carnet, on ne l'invente pas : le verrou se tait et le verdict le laisse voir.
        prof = None
        st = (carnet or {}).get(coin)
        if st and (st.get("bid_depth_usd") or st.get("ask_depth_usd")):
            prof = (float(st.get("bid_depth_usd") or 0.0) + float(st.get("ask_depth_usd") or 0.0)) / 2.0

        v = encadrer_le_market_making(coin, trades, spread_bps=sp, profondeur_devant_usd=prof)
        verdicts.append(v)
        d = next((b for b in v.bornes if b.nom == "DERRIERE"), None)
        if d is None or d.net_bps is None:
            print("  %-10s %6d %7.1f  %9s  %-19s  %s"
                  % (coin, v.n_trades, sp, "--", "--", v.verdict[:60]))
            continue
        print("  %-10s %6d %7.1f  %+8.1fb  [%+6.1f ; %+6.1f]  %s"
              % (coin, d.n_fills, sp, d.adverse_bps, d.net_ic_bas, d.net_ic_haut,
                 d.verdict[:60]))

    candidats = [
        v for v in verdicts
        if any(b.nom == "DERRIERE" and b.verdict.startswith("CANDIDAT") for b in v.bornes)
    ]
    print()
    if not candidats:
        print("  " + "-" * 76)
        print("  >>> AUCUN MARCHE NE PAIE, A LA PLACE QUI EST LA NOTRE.")
        print("  " + "-" * 76)
        print("      Ce n'est pas une panne : c'est une reponse. Soit personne ne traverse le")
        print("      spread, soit le prix nous punit apres nous avoir remplis, soit le signe")
        print("      tient dans son intervalle de confiance -- donc c'est du bruit.")
        print()
        print("      Ce verdict n'utilise AUCUNE hypothese de file inventee : `net_bps` est")
        print("      capture - frais - selection adverse. Aucun 10 % la-dedans.\n")
    else:
        print("  >>> %d marche(s) CANDIDAT(S) a la borne realiste :" % len(candidats))
        for v in candidats:
            d = next(b for b in v.bornes if b.nom == "DERRIERE")
            print("      %-10s net %+.1f bps [%+.1f ; %+.1f]  plafond %.2f $/h"
                  % (v.coin, d.net_bps, d.net_ic_bas, d.net_ic_haut, d.pnl_max_par_h_usd))
        print()
        print("      ATTENTION : le 'plafond' suppose qu'on capture 100 %% du flux qui nous")
        print("      atteint -- ce qui est IMPOSSIBLE (les MM pros sont devant nous). Le reel")
        print("      sera plus bas. C'est une BORNE, pas une prevision, et surement pas un PnL.\n")

    sortie = ROOT / "data" / "reports" / "market_making_bornes.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps([v.as_dict() for v in verdicts], indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print("  rapport : %s\n" % sortie.relative_to(ROOT))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=240.0)   # 4 h : sous 30 min, aucun debit n'est mesurable
    ap.add_argument("--verdict-seulement", action="store_true")
    ap.add_argument("--inclure", default="KAITO",
                    help="marches a ecouter QUOI QU'IL ARRIVE (liste separee par des virgules). "
                         "KAITO par defaut : c'est la piece que T1 doit trancher, et un seuil de "
                         "profondeur l'excluait silencieusement.")
    args = ap.parse_args()

    carnet = _carnet_par_coin()
    if not carnet:
        print("\n  Aucun carnet. Lance MESURER-SPREAD-CARNET.cmd d'abord.\n")
        return 2

    forces = [c.strip().upper() for c in str(args.inclure or "").split(",") if c.strip()]
    spreads = univers_d_ecoute(carnet, forces)
    if not spreads:
        print("\n  Aucun marche dont le spread couvre les frais.\n")
        return 2

    print("\n  %d marches ECOUTES (spread > frais, + forces : %s) :"
          % (len(spreads), ", ".join(forces) or "-"))
    for c, sp in sorted(spreads.items(), key=lambda kv: -(kv[1] if kv[1] == kv[1] else -1)):
        st = carnet.get(c, {})
        marque = "  <<< FORCE" if c in forces else ""
        print("    %-11s spread %6.1f bps  profondeur %6.0f/%6.0f$  (%d releves)%s"
              % (c, sp, st.get("bid_depth_usd", 0.0), st.get("ask_depth_usd", 0.0),
                 st.get("n_releves", 0), marque))
    print("\n  NB : la profondeur ne filtre PAS l'ecoute (ecouter ne coute rien et n'engage rien).")
    print("  Elle est rappelee ici parce qu'elle pesera sur le VERDICT.\n")

    if args.verdict_seulement:
        return _verdict(spreads, carnet)

    print("  Ecoute du canal PUBLIC `trades` pendant %.0f min... (lecture seule)" % args.minutes)
    print("  (aucun ordre, aucune cle, aucune signature -- on ECOUTE)\n")
    try:
        res = asyncio.run(enregistrer(list(spreads), DOSSIER, duree_s=args.minutes * 60.0))
    except KeyboardInterrupt:
        print("\n  interrompu -- on passe au verdict sur ce qui a ete capte\n")
        return _verdict(spreads, carnet)
    except Exception as exc:
        print("  ECHEC de l'ecoute : %s\n" % exc)
        return 3

    print("  %d trades enregistres  (%d doublons ignores, %d reconnexion(s))"
          % (res["trades_enregistres"], res.get("doublons_ignores", 0),
             res.get("reconnexions", 0)))
    for c, n in sorted(res["par_coin"].items(), key=lambda kv: -kv[1]):
        print("    %-11s %d" % (c, n))
    return _verdict(spreads)


if __name__ == "__main__":
    sys.exit(main())
