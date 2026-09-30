#!/usr/bin/env python3
"""FALSIFIER LE CARRY DELTA-NEUTRE (T2, 2026-07-12).

`mesurer_carry_neutre.py` sort UN candidat : HYPE, "+86,7 bps nets sur 30 jours, VIABLE".
Apres T1, on sait ce que vaut un candidat qu'on n'a pas essaye de detruire : rien.

CINQ ATTAQUES. Chacune peut le tuer. Toutes sont mesurables sur des donnees PUBLIQUES.

  A1 -- COLLISION DE TICKER. 4 coins sur 8 sortent une base impossible (TRUMP : +84 935 946 bps).
        L'outil les "ecarte comme bug de mapping". **Ce n'est PAS un bug de lecture.** HIP-1
        laisse N'IMPORTE QUI deployer un token spot avec N'IMPORTE QUEL ticker. Le spot "TRUMP"
        d'Hyperliquid n'est PAS l'actif du perp "TRUMP". Couvrir un perp avec un homonyme, ce
        n'est pas une couverture : ce sont DEUX paris nus. Il faut le PROUVER par le prix.

  A2 -- LE FUNDING EST MODELISE, PAS MESURE. Le modele prend le funding d'AUJOURD'HUI et le
        projette 30 jours en supposant qu'il reste POSITIF. Or un funding negatif = le short
        PAIE. `fundingHistory` donne le funding REEL, heure par heure. On ne modelise plus :
        on relit ce qu'un short aurait VRAIMENT encaisse.

  A3 -- LA BASE EST CREDITEE COMME UN GAIN. `cout_entree = frais - base`. Faux : on ne capture
        la base que si elle CONVERGE. Si elle vaut +2,6 bps a l'entree ET a la sortie, on
        capture ZERO. La base est un RISQUE d'esperance nulle, pas un cadeau. `fundingHistory`
        donne aussi le `premium` (= la base) : on peut mesurer sa VOLATILITE.

  A4 -- LA LIQUIDITE SPOT EST UN NOMBRE INVENTE. `vol24 / 24 / 60 * 5` = "~5 minutes de volume".
        C'est le "10 % du flux" de T1 sous un autre nom. On lit le CARNET.

  A5 -- LA JAMBE PERP PEUT ETRE LIQUIDEE (X-08). Delta-neutre ne veut PAS dire sans risque :
        le spot ne sert PAS de marge au perp. Si le prix monte fort, le short perp saute --
        et on reste long spot a nu, exactement ce qu'on voulait eviter.

LECTURE SEULE. Endpoints /info publics. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.funding.delta_neutral_carry import (  # noqa: E402
    COUT_MAKER_2_JAMBES_BPS,
    COUT_TAKER_2_JAMBES_BPS,
    cout_aller_retour_bps,
)

API = "https://api.hyperliquid.xyz/info"

JOURS_HISTORIQUE = 90
BASE_MAX_MEME_ACTIF_BPS = 200.0   # au-dela, le perp et le spot ne cotent PAS le meme actif

# Il faut ~1000 x la taille d'une jambe de 500 $ en volume quotidien pour pouvoir la monter
# PUIS en sortir sans etre soi-meme le marche. Un carnet sans flux ne se regarnit pas.
VOLUME_SPOT_MIN_24H_USD = 500_000.0

TAILLE_JAMBE_USD = 500.0          # la taille qu'on veut REELLEMENT monter, pas une abstraction


def _post(payload: dict):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=25.0) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------ A2 + A3 : l'histoire reelle

def historique_funding(coin: str, jours: int = JOURS_HISTORIQUE) -> list[dict]:
    """Le funding REEL, heure par heure. Pas un modele : un releve.

    PAGINATION -- LE BUG DE MON PROPRE OUTIL (2026-07-12).
    `fundingHistory` plafonne sa reponse a **500 entrees**. Un appel unique sur 90 jours ne
    rendait donc que 500 h = 21 jours, en silence. Consequence : la "pire fenetre de 30 jours"
    etait incalculable, et les 4 coins sortaient INSUFFICIENT_DATA. Un refus honnete, certes --
    mais pour une mauvaise raison : ce n'etait pas la donnee qui manquait, c'etait moi qui ne
    la demandais pas. Une limite d'API silencieuse est un piege, exactement comme le mount.
    """
    debut_ms = int((time.time() - jours * 86400) * 1000)
    fin_ms = int(time.time() * 1000)
    out: list[dict] = []
    vus: set[int] = set()
    curseur = debut_ms
    for _ in range(40):                        # borne dure : jamais de boucle infinie
        try:
            lot = _post({"type": "fundingHistory", "coin": coin,
                         "startTime": curseur, "endTime": fin_ms})
        except Exception as exc:
            print("      (echec fundingHistory %s : %s)" % (coin, exc))
            break
        if not isinstance(lot, list) or not lot:
            break
        neuf = 0
        for e in lot:
            try:
                t = int(e["time"])
            except (KeyError, TypeError, ValueError):
                continue
            if t not in vus:
                vus.add(t)
                out.append(e)
                neuf += 1
        if neuf == 0:                          # l'API ne rend plus rien de nouveau -> fini
            break
        dernier = max(int(e["time"]) for e in lot if "time" in e)
        if dernier <= curseur:
            break
        curseur = dernier + 1
        if curseur >= fin_ms:
            break
    out.sort(key=lambda e: int(e.get("time") or 0))
    return out


def realise(hist: list[dict]) -> dict | None:
    """Ce qu'un SHORT perp aurait VRAIMENT encaisse. Signe compris."""
    taux, prem = [], []
    for e in hist:
        try:
            taux.append(float(e["fundingRate"]) * 10_000.0)      # bps / h
            prem.append(float(e.get("premium") or 0.0) * 10_000.0)
        except (KeyError, TypeError, ValueError):
            continue
    if len(taux) < 24:
        return None

    cumule = sum(taux)                                # bps encaisses sur toute la periode
    heures = len(taux)
    negatifs = sum(1 for t in taux if t < 0)

    # la PIRE fenetre glissante de 30 jours (720 h) : c'est elle qui decide, pas la moyenne
    f = 720
    pire = None
    if heures >= f:
        s = sum(taux[:f])
        pire = s
        for i in range(f, heures):
            s += taux[i] - taux[i - f]
            pire = min(pire, s)

    return {
        "heures": heures,
        "cumule_bps": cumule,
        "moyenne_bps_h": cumule / heures,
        "part_negative": 100.0 * negatifs / heures,
        "pire_fenetre_30j_bps": pire,
        "base_moyenne_bps": statistics.mean(prem) if prem else 0.0,
        "base_ecart_type_bps": statistics.pstdev(prem) if len(prem) > 1 else 0.0,
        "base_min_bps": min(prem) if prem else 0.0,
        "base_max_bps": max(prem) if prem else 0.0,
    }


# ------------------------------------------------------------------ A4 : le VRAI carnet spot

def _slippage_bps(niveaux: list, mid: float, taille_usd: float) -> float | None:
    """Le VRAI cout de traverser le carnet pour `taille_usd` -- pas un demi-spread suppose.

    On MARCHE le carnet, niveau par niveau, et on compare le prix moyen obtenu au mid.
    Si le carnet n'a pas assez de profondeur cumulee, on rend None : on ne devine pas.
    """
    reste = taille_usd
    cout = 0.0
    for niv in niveaux:
        try:
            px = float(niv["px"])
            dispo = float(niv["sz"]) * px
        except (KeyError, TypeError, ValueError):
            continue
        if px <= 0 or dispo <= 0:
            continue
        pris = min(reste, dispo)
        cout += pris * px
        reste -= pris
        if reste <= 1e-9:
            break
    if reste > 1e-9 or taille_usd <= 0 or mid <= 0:
        return None                       # carnet trop mince pour cette taille : on ne ment pas
    px_moyen = cout / taille_usd
    return abs(px_moyen - mid) / mid * 10_000.0


def carnet(coin: str, taille_usd: float = 500.0) -> dict | None:
    """Profondeur au meilleur prix, spread, ET slippage reel pour une jambe de `taille_usd`."""
    try:
        b = _post({"type": "l2Book", "coin": coin})
    except Exception:
        return None
    niveaux = (b or {}).get("levels") or []
    if len(niveaux) < 2 or not niveaux[0] or not niveaux[1]:
        return None
    bids, asks = niveaux[0], niveaux[1]
    try:
        pb, pa = float(bids[0]["px"]), float(asks[0]["px"])
        sb = float(bids[0]["sz"]) * pb
        sa = float(asks[0]["sz"]) * pa
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if pb <= 0 or pa <= 0:
        return None
    mid = (pb + pa) / 2.0
    return {
        "mid": mid, "spread_bps": (pa - pb) / mid * 10_000.0,
        "bid_usd": sb, "ask_usd": sa,
        # ACHAT -> on leve les asks. VENTE -> on tape les bids. Les deux comptent : on entre ET on sort.
        "slip_achat_bps": _slippage_bps(asks, mid, taille_usd),
        "slip_vente_bps": _slippage_bps(bids, mid, taille_usd),
    }


def main() -> int:
    print("\n" + "=" * 78)
    print(" T2 -- FALSIFICATION DU CARRY DELTA-NEUTRE")
    print("=" * 78)

    try:
        meta_perp, ctx_perp = _post({"type": "metaAndAssetCtxs"})
        spot = _post({"type": "spotMetaAndAssetCtxs"})
    except Exception as exc:
        print("  ECHEC reseau : %s\n" % exc)
        return 3

    perps = {}
    for a, c in zip(meta_perp.get("universe") or [], ctx_perp or []):
        nom = str(a.get("name") or "").upper()
        if nom and isinstance(c, dict):
            try:
                perps[nom] = {"mark": float(c.get("markPx") or 0.0),
                              "funding_bps_h": float(c.get("funding") or 0.0) * 10_000.0,
                              "levier_max": float(a.get("maxLeverage") or 0.0)}
            except (TypeError, ValueError):
                pass

    spot_meta, spot_ctx = (spot[0], spot[1]) if isinstance(spot, list) and len(spot) == 2 else ({}, [])
    tokens = {int(t["index"]): str(t.get("name") or "").upper()
              for t in (spot_meta.get("tokens") or []) if "index" in t}
    paire_vers_base, base_vers_paire = {}, {}
    for pair in spot_meta.get("universe") or []:
        nom_paire = str(pair.get("name") or "")
        idx = pair.get("tokens") or []
        b = tokens.get(idx[0]) if idx else None
        if nom_paire and b:
            paire_vers_base[nom_paire] = b
            base_vers_paire.setdefault(b, nom_paire)

    # UN MEME TOKEN A PLUSIEURS PAIRES SPOT. On garde LA PLUS LIQUIDE, jamais la derniere vue.
    #
    # MON PROPRE BUG (2026-07-12) -- et il m'aurait fait conclure a l'envers.
    # J'ecrivais `spots[b] = {...}` dans la boucle : la DERNIERE paire rencontree ecrasait les
    # autres. Pour HYPE, je tombais sur `@255` (567 $ de volume / 24 h) au lieu de la vraie
    # paire liquide (31,7 M$). J'ai donc lu le CARNET de la mauvaise paire, mesure un spot
    # mort, et j'allais declarer "SPOT MORT" un marche qui brasse 31 millions par jour.
    #
    # Deux outils ont donne deux chiffres pour la meme chose (567 $ contre 31,7 M$). Quand
    # deux mesures se contredisent, l'une est fausse -- et il faut trouver LAQUELLE avant de
    # conclure quoi que ce soit. Jamais moyenner, jamais choisir la plus commode.
    spots = {}
    for c in spot_ctx or []:
        if not isinstance(c, dict):
            continue
        b = paire_vers_base.get(str(c.get("coin") or ""))
        if not b:
            continue
        try:
            px = float(c.get("markPx") or c.get("midPx") or 0.0)
            vol = float(c.get("dayNtlVlm") or 0.0)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        ancien = spots.get(b)
        if ancien is None or vol > ancien["vol24"]:
            spots[b] = {"mark": px, "paire": str(c.get("coin")), "vol24": vol}

    communs = sorted(set(perps) & set(spots))
    print("\n  %d perps - %d spots - %d coins portent LE MEME NOM\n" % (len(perps), len(spots), len(communs)))

    # ---------------------------------------------------------------- A1
    print("=" * 78)
    print(" A1 -- MEME NOM = MEME ACTIF ? (HIP-1 laisse deployer n'importe quel ticker)")
    print("=" * 78)
    vrais: list[str] = []
    for c in communs:
        p, s = perps[c], spots[c]
        if p["mark"] <= 0 or s["mark"] <= 0:
            continue
        base = (p["mark"] - s["mark"]) / s["mark"] * 10_000.0
        meme = abs(base) <= BASE_MAX_MEME_ACTIF_BPS
        print("  %-8s perp %14.6f   spot %14.6f   ecart %+14.1f bps   %s"
              % (c, p["mark"], s["mark"], base,
                 "MEME ACTIF" if meme else "*** COLLISION DE TICKER -- PAS LE MEME ACTIF ***"))
        if meme:
            vrais.append(c)
    print()
    print("  >>> %d coin(s) sur %d sont VRAIMENT couvrables. Les autres sont des HOMONYMES :"
          % (len(vrais), len(communs)))
    print("      un perp couvert par un token qui porte le meme nom mais cote 800x moins")
    print("      n'est pas couvert. Ce sont DEUX paris nus qui s'ignorent.\n")
    if not vrais:
        print("  >>> AUCUNE COUVERTURE POSSIBLE. T2 est clos.\n")
        return 2

    # ---------------------------------------------------------------- A2 + A3
    print("=" * 78)
    print(" A2 -- LE FUNDING REELLEMENT ENCAISSE (%d jours d'historique, pas un modele)" % JOURS_HISTORIQUE)
    print(" A3 -- LA BASE : un RISQUE d'esperance nulle, pas un cadeau")
    print("=" * 78)
    resultats = {}
    for c in vrais:
        h = historique_funding(c)
        r = realise(h)
        if not r:
            print("  %-8s pas assez d'historique -> INSUFFICIENT_DATA" % c)
            continue
        resultats[c] = r
        print("\n  %s" % c)
        print("    funding encaisse par un SHORT sur %d h (%.0f j) : %+.1f bps"
              % (r["heures"], r["heures"] / 24.0, r["cumule_bps"]))
        print("    moyenne %+.4f bps/h   |   heures ou le short A PAYE : %.1f %%"
              % (r["moyenne_bps_h"], r["part_negative"]))
        if r["pire_fenetre_30j_bps"] is not None:
            print("    PIRE fenetre de 30 jours : %+.1f bps   <- c'est ELLE qui decide"
                  % r["pire_fenetre_30j_bps"])
        print("    base (premium) : moyenne %+.1f bps, ecart-type %.1f bps, min %+.1f / max %+.1f"
              % (r["base_moyenne_bps"], r["base_ecart_type_bps"],
                 r["base_min_bps"], r["base_max_bps"]))

    # ---------------------------------------------------------------- A4
    print("\n" + "=" * 78)
    print(" A4 -- LE CARNET SPOT REEL (plus de 'liquidite' inventee depuis le volume 24 h)")
    print("=" * 78)
    carnets, carnets_perp = {}, {}
    for c in vrais:
        paire = spots[c]["paire"]
        k = carnet(paire, TAILLE_JAMBE_USD)
        cp = carnet(c, TAILLE_JAMBE_USD)
        if not k:
            print("  %-8s carnet spot ILLISIBLE -> on ne conclut pas" % c)
            continue
        carnets[c] = k
        v = float(spots[c].get("vol24") or 0.0)
        vs = ("%.1f M$" % (v / 1e6)) if v >= 1e6 else ("%.0f k$" % (v / 1e3))
        print("  %-8s SPOT (%s) : spread %5.1f bps   profondeur bid %8.0f $ / ask %8.0f $"
              % (c, paire, k["spread_bps"], k["bid_usd"], k["ask_usd"]))
        print("           volume spot 24 h : %-10s %s"
              % (vs, "" if v >= VOLUME_SPOT_MIN_24H_USD
                 else "<<< SOUS LE PLANCHER : ce carnet ne se regarnit pas"))
        if cp:
            carnets_perp[c] = cp
            print("           PERP        : spread %5.1f bps   profondeur bid %8.0f $ / ask %8.0f $"
                  % (cp["spread_bps"], cp["bid_usd"], cp["ask_usd"]))

    # ---------------------------------------------------------------- LE VERDICT
    print("\n" + "=" * 78)
    print(" VERDICT -- funding REEL  -  (frais + SPREAD des 2 carnets), et le risque nomme")
    print("=" * 78)
    print("  LE SPREAD ETAIT ABSENT DU MODELE. C'est le poste DOMINANT sur ces carnets :")
    print("  sur PURR, 80 bps de spread contre 18 bps de frais. On paie 13x ce qu'on comptait.")
    print("  La base n'est PAS creditee : on ne la capture que si elle CONVERGE.\n")
    print("  %-8s %9s %9s %10s %11s %11s  %s"
          % ("coin", "spr.spot", "spr.perp", "cout A/R", "30j MOYEN", "30j PIRE", "verdict"))
    print("  %-8s %9s %9s %10s %11s %11s  %s"
          % ("-"*8, "-"*9, "-"*9, "-"*10, "-"*11, "-"*11, "-"*24))

    viables = []
    for c in vrais:
        r = resultats.get(c)
        k = carnets.get(c)
        kp = carnets_perp.get(c)
        if not r:
            continue
        if not k or not kp:
            print("  %-8s carnet non lu -> INSUFFICIENT_DATA, on ne tranche pas" % c)
            continue

        # VERROU DE FLUX SPOT : un carnet n'est pas de la liquidite.
        # AZTEC affiche 220 $ a l'ask... et **0 $ de volume spot sur 24 h**. Un carnet
        # sans flux ne se REGARNIT pas : on ne peut ni monter la jambe, ni en sortir.
        # C'est la lecon de T1 transposee : la profondeur affichee ment, le FLUX ne ment pas.
        vol_spot = float(spots[c].get("vol24") or 0.0)
        if vol_spot < VOLUME_SPOT_MIN_24H_USD:
            print("  %-8s %8.1fb %8.1fb %9s %11s %11s  SPOT MORT : %.0f $ de volume / 24 h"
                  % (c, k["spread_bps"], kp["spread_bps"], "--", "--", "--", vol_spot))
            continue

        # TAKER, avec le SLIPPAGE REEL mesure en traversant les 4 carnets qu'on va traverser :
        #   entree : ACHAT spot (on leve les asks) + VENTE perp (on tape les bids)
        #   sortie : VENTE spot (on tape les bids) + ACHAT perp (on leve les asks)
        # Si un seul des quatre n'a pas la profondeur, on REFUSE : la jambe ne se monte pas.
        quatre = [k.get("slip_achat_bps"), k.get("slip_vente_bps"),
                  kp.get("slip_vente_bps"), kp.get("slip_achat_bps")]
        if any(x is None for x in quatre):
            print("  %-8s %8.1fb %8.1fb %9s %11s %11s  CARNET TROP MINCE POUR %.0f $ -> NO_TRADE"
                  % (c, k["spread_bps"], kp["spread_bps"], "--", "--", "--", TAILLE_JAMBE_USD))
            continue
        cout = COUT_TAKER_2_JAMBES_BPS + sum(quatre)

        pire = r["pire_fenetre_30j_bps"]
        net_moyen = r["moyenne_bps_h"] * 720.0 - cout
        if pire is None:
            print("  %-8s %8.1fb %8.1fb %9.1fb %+10.1fb %11s  MOINS DE 30 J -> INSUFFICIENT_DATA"
                  % (c, k["spread_bps"], kp["spread_bps"], cout, net_moyen, "--"))
            continue
        net_pire = pire - cout
        ok = net_pire > 0
        print("  %-8s %8.1fb %8.1fb %9.1fb %+10.1fb %+10.1fb  %s"
              % (c, k["spread_bps"], kp["spread_bps"], cout, net_moyen, net_pire,
                 "TIENT MEME AU PIRE" if ok else "PERD DANS SON PIRE MOIS"))
        if ok:
            viables.append((c, net_pire, net_moyen, cout))

    print()
    if not viables:
        print("  " + "-" * 74)
        print("  >>> AUCUN CARRY DELTA-NEUTRE NE TIENT. NO_TRADE.")
        print("  " + "-" * 74)
        print("      Ce n'est pas une panne : c'est une reponse. Le funding est reel, mais il")
        print("      ne paie ni le spread des deux carnets, ni ses propres mois negatifs.\n")
    else:
        for c, np_, nm, cout in viables:
            k, kp = carnets.get(c), carnets_perp.get(c)
            print("  >>> %s : %+.1f bps / 30 j dans le PIRE mois observe, %+.1f bps en moyenne."
                  % (c, np_, nm))
            print("      Sur %.0f $ : %.2f $ dans le pire mois, %.2f $ en moyenne."
                  % (TAILLE_JAMBE_USD, np_ * TAILLE_JAMBE_USD / 10_000,
                     nm * TAILLE_JAMBE_USD / 10_000))
            if k and kp:
                print("      Slippage REEL mesure en traversant les carnets pour %.0f $ :"
                      % TAILLE_JAMBE_USD)
                print("        spot achat %.2f bps | spot vente %.2f bps | "
                      "perp vente %.2f bps | perp achat %.2f bps"
                      % (k["slip_achat_bps"], k["slip_vente_bps"],
                         kp["slip_vente_bps"], kp["slip_achat_bps"]))
                print("        -> cout total aller-retour : %.1f bps (frais %.0f + slippage %.1f)"
                      % (cout, COUT_TAKER_2_JAMBES_BPS, cout - COUT_TAKER_2_JAMBES_BPS))
        print()
        print("  " + "!" * 74)
        print("  A5 -- LE RISQUE QUI RESTE, ET IL N'EST PAS MODELISE :")
        print("      Le spot ne sert PAS de marge au perp sur Hyperliquid. Un delta-neutre")
        print("      N'EST PAS sans risque : si le prix monte fort, la jambe SHORT perp peut")
        print("      etre LIQUIDEE pendant que la jambe spot, elle, va bien. On se reveille")
        print("      LONG SPOT A NU -- exactement le pari qu'on voulait supprimer.")
        print("      Un carry sans plan de marge est un pari directionnel a retardement.")
        print("  " + "!" * 74)
    print()

    out = ROOT / "data" / "reports" / "t2_falsification_carry.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "coins_meme_nom": communs, "coins_meme_actif": vrais,
        "funding_realise": resultats,
        "carnets_spot": carnets, "carnets_perp": carnets_perp,
        "frais_2_jambes_maker_bps": COUT_MAKER_2_JAMBES_BPS,
        "frais_2_jambes_taker_bps": COUT_TAKER_2_JAMBES_BPS,
        "note_cout": "le cout REEL = frais + spread des deux carnets (taker par defaut)",
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  rapport : %s\n" % out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
