#!/usr/bin/env python3
"""EXISTE-T-IL UN MARCHE OU LE MARKET MAKING EST POSSIBLE ? (2026-07-12)

Chez Hyperliquid le maker **PAIE** 0,015 % (1,5 bps) -- pas de rebate avant les tiers
institutionnels. Aller-retour maker/maker = **3,0 bps**.

LES TROIS FILTRES, DANS CET ORDRE. Un seul echec = mort.

  1. PROFONDEUR   -- peut-on seulement POSER l'ordre ? Un spread de 77 bps sur un carnet a
                     200 $ n'est pas une opportunite : c'est un marche que personne ne veut.
                     Si la profondeur < ta taille, tu N'ES PAS un market maker : tu ES le carnet.
  2. FRAIS        -- une capture realiste (50 % du spread) doit couvrir les 3 bps.
  3. TOXICITE     -- le prix ne doit pas bouger plus vite que ton spread, sinon tu es rempli
                     PRECISEMENT quand le prix va contre toi. C'est la selection adverse, et
                     c'est ce qui tue les market makers -- pas les frais.

CE QUE CE SCRIPT NE PEUT PAS MESURER, ET IL FAUT LE DIRE :
  * le VOLUME qui traverse ton spread (sans flux, un spread large ne rapporte RIEN) ;
  * ta position dans la file d'attente ;
  * le taux de fill reel.
  Ces trois-la demandent le flux de TRADES (canal `trades` du WS), pas des snapshots.
  Ce script elimine les marches IMPOSSIBLES. Il ne prouve PAS qu'un survivant est rentable.

    python tools/mesurer_spread_carnet.py

LECTURE SEULE. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAKER_BPS = 1.5
COUT_ALLER_RETOUR = 2 * MAKER_BPS
CAPTURE_REALISTE = 0.5          # on ne capture jamais tout le spread
TAILLE_VOULUE_USD = 500.0       # le notionnel que le bot place reellement
MARGE_PROFONDEUR = 5.0          # il faut 5x ta taille en face, sinon TU es le carnet
TOXICITE_MAX = 1.0              # bruit > spread => on est ramasse a chaque fois
VOLUME_MIN_24H = 5_000_000.0    # sous ce seuil, personne ne traverse ton spread : desert


def _med(v):
    return statistics.median(v) if v else None


def _volume_depuis_api() -> dict:
    """Volume 24 h par marche, via l'endpoint PUBLIC /info d'Hyperliquid. LECTURE SEULE."""
    import json as _j
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=_j.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            meta, ctxs = _j.loads(resp.read().decode("utf-8"))
    except Exception as exc:                       # pas de reseau -> etat vide honnete
        print("  (volume non recupere : %s)" % exc)
        return {}

    noms = [str(a.get("name") or "").upper() for a in (meta.get("universe") or [])]
    out = {}
    for nom, ctx in zip(noms, ctxs or []):
        if not nom or not isinstance(ctx, dict):
            continue
        try:
            v = float(ctx.get("dayNtlVlm") or 0.0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[nom] = v
    print("  volume 24 h recupere pour %d marches (API publique, lecture seule)" % len(out))
    return out


def main() -> int:
    lignes = []
    for f in sorted(ROOT.glob("runtime/replay/l2_book*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    lignes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not lignes:
        print("\n  AUCUN releve de carnet. Laisse le bot tourner, puis relance.\n")
        return 2

    par = defaultdict(list)
    for r in lignes:
        if r.get("coin"):
            par[r["coin"]].append(r)

    # VOLUME 24 h -- le 4e filtre, et le plus dur.
    # Un market maker gagne = spread x volume echange CONTRE LUI. Sur un marche que personne ne
    # traverse, un spread de 49 bps ne rapporte RIEN : on porte juste l'inventaire.
    volume = {}
    for f in sorted(ROOT.glob("runtime/replay/funding*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                v = r.get("day_ntl_volume_usd")
                if r.get("coin") and v:
                    volume[r["coin"]] = float(v)      # le dernier releve fait foi

    # Repli : si le volume n'est pas encore dans les fichiers (recorder corrige le 2026-07-12),
    # on le demande UNE FOIS a l'API publique Hyperliquid. Lecture seule, endpoint /info public,
    # exactement ce que le bot fait deja. Aucun ordre, aucune cle, aucune signature.
    if not volume:
        volume.update(_volume_depuis_api())

    print("\n  %d releves - %d marches" % (len(lignes), len(par)))
    print("  Cout aller-retour maker/maker : %.1f bps" % COUT_ALLER_RETOUR)
    print("  Taille visee : $%.0f  (il faut $%.0f au carnet pour ne pas ETRE le carnet)\n"
          % (TAILLE_VOULUE_USD, TAILLE_VOULUE_USD * MARGE_PROFONDEUR))

    rangs = []
    for c, v in par.items():
        if len(v) < 3:
            continue
        sp = _med([float(x["spread_bps"]) for x in v if x.get("spread_bps") is not None])
        if sp is None or sp <= 0:
            continue
        bd = _med([float(x.get("bid_depth_usd") or 0.0) for x in v]) or 0.0
        ad = _med([float(x.get("ask_depth_usd") or 0.0) for x in v]) or 0.0
        prof = min(bd, ad)

        serie = sorted((float(x["ts"]), float(x["mid"])) for x in v
                       if x.get("ts") and x.get("mid"))
        moves = [abs(serie[i + 1][1] - serie[i][1]) / serie[i][1] * 10_000.0
                 for i in range(len(serie) - 1) if serie[i][1] > 0]
        bruit = _med(moves)
        toxicite = (bruit / sp) if (bruit is not None and sp > 0) else None

        capture = sp * CAPTURE_REALISTE
        net = capture - COUT_ALLER_RETOUR

        vol = volume.get(c)

        # --- LES QUATRE FILTRES. Un seul echec = mort.
        if vol is None:
            verdict, ok = "volume INCONNU -> refus", False
            rangs.append((c, sp, prof, net, toxicite, vol, verdict, ok))
            continue
        if vol < VOLUME_MIN_24H:
            verdict, ok = "DESERT ($%.0fk/24h)" % (vol / 1000.0), False
            rangs.append((c, sp, prof, net, toxicite, vol, verdict, ok))
            continue
        if prof < TAILLE_VOULUE_USD:
            verdict, ok = "carnet VIDE (< $%.0f)" % TAILLE_VOULUE_USD, False
        elif prof < TAILLE_VOULUE_USD * MARGE_PROFONDEUR:
            verdict, ok = "TU ES le carnet (trop mince)", False
        elif net <= 0:
            verdict, ok = "le spread ne couvre pas les frais", False
        elif toxicite is None:
            verdict, ok = "toxicite inconnue -> refus", False
        elif toxicite > TOXICITE_MAX:
            verdict, ok = "TOXIQUE (bruit %.1fx le spread)" % toxicite, False
        else:
            verdict, ok = "SURVIVANT -- a verifier sur le flux", True

        rangs.append((c, sp, prof, net, toxicite, vol, verdict, ok))

    rangs.sort(key=lambda x: (-int(x[7]), -x[3]))

    print("  %-11s %8s %10s %8s %9s %9s  %s"
          % ("coin", "spread", "profond.", "net", "toxicite", "vol 24h", "verdict"))
    print("  %-11s %8s %10s %8s %9s %9s  %s"
          % ("-" * 11, "-" * 8, "-" * 10, "-" * 8, "-" * 9, "-" * 9, "-" * 32))

    survivants = [r for r in rangs if r[7]]
    for c, sp, prof, net, tox, vol, verdict, ok in rangs[:25]:
        t = "--" if tox is None else "%.1fx" % tox
        v = "--" if vol is None else ("%.1fM" % (vol / 1e6) if vol >= 1e6 else "%.0fk" % (vol / 1e3))
        print("  %-11s %7.1fb %9.0f$ %+7.2fb %9s %9s  %s" % (c, sp, prof, net, t, v, verdict))

    tous = sorted(float(x["spread_bps"]) for v in par.values() for x in v
                  if x.get("spread_bps") is not None)
    print("\n  spread median global : %.2f bps" % tous[len(tous) // 2])
    print("  volume minimum exige : $%.0fM / 24h" % (VOLUME_MIN_24H / 1e6))
    print("  survivants aux 3 filtres : %d / %d marches\n" % (len(survivants), len(rangs)))

    if not survivants:
        print("  " + "-" * 74)
        print("  >>> AUCUN MARCHE NE SURVIT. Ce n'est pas une panne, c'est une reponse.")
        print("  " + "-" * 74)
        print("      Les spreads larges sont sur des marches DESERTS, des carnets vides, ou des")
        print("      prix qui te passent dessus. Les carnets profonds ont des spreads 10x plus")
        print("      petits que les frais. Le market making retail n'a pas d'espace ici.\n")
    else:
        print("  >>> %d marche(s) survivent aux 4 filtres." % len(survivants))
        print("      Survivre n'est PAS gagner. Il reste la position dans la FILE D'ATTENTE :")
        print("      sur un spread large, les autres MM se placent devant toi. Pour etre rempli,")
        print("      il faut resserrer -- donc capturer MOINS que les 50 %% supposes ici.")
        print("      Seul le canal `trades` (fills reels, cote par cote) tranchera.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
