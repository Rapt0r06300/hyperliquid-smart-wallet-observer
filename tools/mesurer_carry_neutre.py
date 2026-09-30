#!/usr/bin/env python3
"""LE CARRY DELTA-NEUTRE : LA VOIE DE REOUVERTURE (2026-07-12).

    LONG spot + SHORT perp, meme taille  ->  le prix s'annule. Il ne reste que le funding.

C'est litteralement le "grinder" que Flo demande depuis le debut : beaucoup de mini-positions,
zero pari directionnel. Et c'est la SEULE voie que la zone morte `FUNDING_JAMBE_NUE` designe
elle-meme comme reouverture.

Le funding est le seul signal de tout ce projet qui ait une structure reelle :
autocorrelation +0,70 a une heure. Il est PREVISIBLE. Ce qui le tuait, c'etait la jambe NUE.

CE SCRIPT VA CHERCHER LES DONNEES QU'ON N'A JAMAIS REGARDEES : le marche SPOT d'Hyperliquid.

    python tools/mesurer_carry_neutre.py

LECTURE SEULE. Endpoints /info publics. Aucune cle, aucune signature, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.funding.delta_neutral_carry import (  # noqa: E402
    COUT_MAKER_2_JAMBES_BPS,
    COUT_TAKER_2_JAMBES_BPS,
    evaluer_carry_neutre,
)

API = "https://api.hyperliquid.xyz/info"

# Au-dela de 20 %, un ecart perp/spot n'est pas une base : c'est un bug de mapping.
# (Une vraie base d'arbitrage vit entre -100 et +300 bps. 2000 bps est deja tres genereux.)
BASE_ABERRANTE_BPS = 2000.0


def _post(payload: dict):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20.0) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print("\n  Lecture des marches PERP et SPOT d'Hyperliquid (public, lecture seule)...")
    try:
        meta_perp, ctx_perp = _post({"type": "metaAndAssetCtxs"})
        spot = _post({"type": "spotMetaAndAssetCtxs"})
    except Exception as exc:
        print("  ECHEC reseau : %s\n" % exc)
        return 3

    # --- perps : funding + prix mark
    perps = {}
    for a, c in zip(meta_perp.get("universe") or [], ctx_perp or []):
        nom = str(a.get("name") or "").upper()
        if not nom or not isinstance(c, dict):
            continue
        try:
            perps[nom] = {
                "funding_bps_h": float(c.get("funding") or 0.0) * 10_000.0,
                "mark": float(c.get("markPx") or 0.0),
                "vol24": float(c.get("dayNtlVlm") or 0.0),
            }
        except (TypeError, ValueError):
            continue

    # --- spot : prix + liquidite.
    #
    # BUG CORRIGE (2026-07-12) -- CET OUTIL A SORTI DES CHIFFRES IMPOSSIBLES.
    #   HYPE base = +177 721 383 bps  (le perp vaudrait 17 772 x le spot)
    #   HYPE spot 24h = 0 $           (le token maison d'Hyperliquid, zero volume ?!)
    # Seul PURR etait realiste (+16,1 bps) -- et c'est LA SEULE paire qu'Hyperliquid nomme
    # explicitement (les autres sont "@1", "@2"...). Autrement dit : le `zip(universe, ctxs)`
    # ne s'alignait QUE sur elle. Pour les autres, je comparais le perp HYPE au spot d'un token
    # tire au hasard.
    #
    # LE VRAI JOIN : chaque contexte spot porte son propre champ `coin` (= le nom de la paire).
    # On joint donc par NOM, jamais par position. Une position, ca ment en silence ; un nom, non.
    spot_meta, spot_ctx = (spot[0], spot[1]) if isinstance(spot, list) and len(spot) == 2 else ({}, [])
    tokens = {int(t["index"]): str(t.get("name") or "").upper()
              for t in (spot_meta.get("tokens") or []) if "index" in t}

    # nom de paire ("@107", "PURR/USDC") -> token de base ("HYPE", "PURR")
    paire_vers_base: dict[str, str] = {}
    for pair in spot_meta.get("universe") or []:
        nom_paire = str(pair.get("name") or "")
        idx = pair.get("tokens") or []
        base = tokens.get(idx[0]) if idx else None
        if nom_paire and base:
            paire_vers_base[nom_paire] = base

    spots = {}
    for i, c in enumerate(spot_ctx or []):
        if not isinstance(c, dict):
            continue
        # 1) join par NOM (fiable). 2) repli positionnel SEULEMENT si le champ `coin` manque.
        nom_paire = str(c.get("coin") or "")
        base = paire_vers_base.get(nom_paire)
        if not base:
            univers = spot_meta.get("universe") or []
            if i < len(univers):
                base = paire_vers_base.get(str(univers[i].get("name") or ""))
        if not base:
            continue
        try:
            px = float(c.get("markPx") or c.get("midPx") or 0.0)
            vol = float(c.get("dayNtlVlm") or 0.0)
        except (TypeError, ValueError):
            continue
        if px > 0:
            # une meme base peut avoir plusieurs paires : on garde la plus liquide
            ancien = spots.get(base)
            if ancien is None or vol > ancien["vol24"]:
                spots[base] = {"mark": px, "vol24": vol}

    # GARDE-FOU DE BON SENS : un volume spot TOTAL nul est impossible.
    vol_spot_total = sum(s["vol24"] for s in spots.values())
    if spots and vol_spot_total <= 0.0:
        print("  >>> VOLUME SPOT TOTAL = 0 $. C'est IMPOSSIBLE : le champ lu n'est pas le bon.")
        print("      Je REFUSE de conclure sur une mesure fausse.")
        print("      Lance : python tools/diagnostic_spot_hyperliquid.py\n")
        return 4

    communs = sorted(set(perps) & set(spots))
    print("  %d perps - %d marches spot - **%d coins ont LES DEUX**\n" % (len(perps), len(spots), len(communs)))
    if communs:
        print("  Coins couvrables : %s\n" % ", ".join(communs[:30]))

    if not communs:
        print("  AUCUN coin n'a a la fois un perp et un spot. La couverture est IMPOSSIBLE.")
        print("  La zone morte FUNDING_JAMBE_NUE reste fermee.\n")
        return 2

    print("  Cout des DEUX jambes : %.0f bps en maker, %.0f bps en taker"
          % (COUT_MAKER_2_JAMBES_BPS, COUT_TAKER_2_JAMBES_BPS))
    print("  Plancher protocolaire Hyperliquid : 0,125 bps/h PERMANENT (11,6 %% APR au short).")
    print("  Il ne s'eteint pas. Les 6 bps sont rembourses en 48 h, puis c'est du portage pur.\n")

    lignes = []
    aberrants: list[tuple[str, float]] = []
    for c in communs:
        p, s = perps[c], spots[c]
        if p["mark"] <= 0 or s["mark"] <= 0:
            continue
        base_bps = (p["mark"] - s["mark"]) / s["mark"] * 10_000.0
        # GARDE-FOU : une base de +177 721 383 bps n'existe pas. Si on voit ca, ce n'est PAS
        # une opportunite d'arbitrage de reve : c'est un mapping perp<->spot casse. On REFUSE
        # de la traiter comme une donnee, et on le DIT. (Un chiffre impossible ne se commente
        # pas : il se debogue. Voir tools/diagnostic_spot_hyperliquid.py.)
        if abs(base_bps) > BASE_ABERRANTE_BPS:
            aberrants.append((c, base_bps))
            continue
        # liquidite spot exploitable : on prend une fraction prudente du volume 24 h
        liq = s["vol24"] / 24.0 / 60.0 * 5.0            # ~5 minutes de volume spot
        v = evaluer_carry_neutre(coin=c, funding_bps_h=p["funding_bps_h"],
                                 base_bps=base_bps, liquidite_spot_usd=liq, maker=True)
        lignes.append((v, p["vol24"], s["vol24"]))

    lignes.sort(key=lambda x: -(x[0].gain_net_24h_bps or -1e9))

    print("  %-10s %10s %9s %11s %10s %11s  %s"
          % ("coin", "funding/h", "base", "spot 24h", "cout ent.", "net 24h", "verdict"))
    print("  %-10s %10s %9s %11s %10s %11s  %s"
          % ("-"*10, "-"*10, "-"*9, "-"*11, "-"*10, "-"*11, "-"*34))

    viables = []
    for v, volp, vols in lignes[:20]:
        g = "--" if v.gain_net_24h_bps is None else "%+.1fb" % v.gain_net_24h_bps
        sv = ("%.1fM" % (vols/1e6)) if vols >= 1e6 else ("%.0fk" % (vols/1e3))
        print("  %-10s %+9.3fb %+8.1fb %11s %+9.1fb %11s  %s"
              % (v.coin, v.funding_bps_h, v.base_bps, sv, v.cout_entree_bps, g,
                 v.motif if not v.viable else "VIABLE -- %s" % v.note))
        if v.viable:
            viables.append(v)

    print()
    if aberrants:
        print("  " + "!"*74)
        print("  MAPPING PERP<->SPOT CASSE sur %d coin(s) — ECARTE, PAS INTERPRETE :" % len(aberrants))
        for coin, base in aberrants:
            print("      %-10s base = %+.0f bps  (impossible : > %.0f bps)"
                  % (coin, base, BASE_ABERRANTE_BPS))
        print("  Ce n'est PAS une opportunite d'arbitrage : c'est un bug de lecture.")
        print("  Diagnostic : python tools/diagnostic_spot_hyperliquid.py")
        print("  " + "!"*74 + "\n")

    if not viables:
        print("  " + "-"*74)
        print("  >>> AUCUN CARRY DELTA-NEUTRE VIABLE.")
        print("  " + "-"*74)
        print("      Le funding ne rembourse pas les 6 bps des deux jambes avant de s'eteindre,")
        print("      ou le spot est trop mince pour monter la couverture.")
        print("      La zone morte FUNDING_JAMBE_NUE reste fermee -- et c'est une REPONSE.\n")
    else:
        total = sum(v.gain_net_24h_bps or 0.0 for v in viables)
        print("  >>> %d carry(s) delta-neutre(s) VIABLE(S). Gain cumule : %.1f bps / 24 h."
              % (len(viables), total))
        print("      Sur 500 $ par paire : %.2f $ / jour / paire en moyenne."
              % (total / len(viables) * 500 / 10_000))
        print("      ⚠️  ESTIMATION. Le spot Hyperliquid est MINCE : la liquidite affichee est")
        print("      une fraction du volume 24 h, pas une profondeur de carnet mesuree.")
        print("      Prochaine etape : lire le CARNET spot, pas seulement son volume.\n")

    out = ROOT / "data" / "reports" / "carry_delta_neutre.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([v.as_dict() for v, _, _ in lignes], indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("  rapport : %s\n" % out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
