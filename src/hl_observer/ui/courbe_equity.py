"""LA COURBE D'EQUITY, RECONSTRUITE DEPUIS LE LEDGER (21/07).

POURQUOI LE MÉTAGRAPHE ÉTAIT ÉCLATÉ
------------------------------------
Mesure du 21/07 : `equity_history.jsonl` contient **600 points, tous à 1 000,00 $ et
pnl = 0,0**. Amplitude : **zéro**.

La raison : cet historique ne connaît que la pile **copy** — qui est éteinte depuis le 11/07
(0 position, 0 PnL). Le **carry**, seul moteur qui ouvre, n'y entre jamais. Un correctif du
19/07 ajoutait le net carry **au dernier point seulement** (pour ne pas réécrire l'histoire).

Résultat à l'écran : **599 points plats, puis une falaise verticale** de tout le PnL carry
sur le dernier pixel. Le graphe ne « bougeait pas bizarrement » — il dessinait fidèlement une
série morte prolongée d'un saut.

CE QUE FAIT CE MODULE
---------------------
Il reconstruit la courbe depuis **le ledger**, qui est déjà la source de vérité du PnL :
chaque `CLOSE` porte son horodatage et son réalisé. On obtient une équity qui bouge quand
quelque chose se passe, et qui reste plate quand rien ne se passe — ce qui est la vérité.

    equity(t) = capital_initial + Σ réalisé(≤ t)  +  funding réglé courant

Le funding réglé n'a pas d'historique horodaté (il est accru en continu). Il est donc appliqué
**au point courant uniquement**, et le point porte `inclut_funding_courant=True` pour qu'on
sache lequel. On ne rétro-projette rien : réécrire le passé avec une information d'aujourd'hui
est exactement ce que le projet s'interdit.

CAS DÉGÉNÉRÉS, TRAITÉS PLUTÔT QUE SUBIS
----------------------------------------
Zéro événement -> **une ligne plate honnête** à capital initial, marquée `plate=True`. Un
graphe qui invente un mouvement quand rien n'a bougé ment ; un graphe plat qui le DIT ne ment
pas. C'est l'appelant qui décide d'afficher « en attente du premier trade ».

PAPER only : dessiner une courbe n'est pas passer un ordre.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CAPITAL_INITIAL_DEFAUT = 1000.0
#: en dessous, une courbe n'a pas de forme : on le DIT au lieu de dessiner du bruit.
POINTS_MIN_POUR_UNE_FORME = 2


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x else x


def evenements_realises(root: str | Path = ".", *, mode: str = "LIVE",
                        ledger_relpath: str | Path | None = None) -> list[dict[str, Any]]:
    """Les CLOSE du ledger, triés dans le temps : `[{ts_ms, realise, coin, strategie}]`.

    C'est la seule source du réalisé. Une ligne sans horodatage ou sans montant est ignorée —
    on ne devine pas quand un gain a eu lieu.
    """
    from hl_observer.funding.carry_positions_store import LEDGER_RELPATH
    chemin = Path(root) / (ledger_relpath or LEDGER_RELPATH)
    out: list[dict[str, Any]] = []
    try:
        for ligne in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                r = json.loads(ligne)
            except ValueError:
                continue
            if not isinstance(r, dict) or r.get("kind") != "CLOSE":
                continue
            if r.get("mode") != mode:
                continue
            ts, pnl = _f(r.get("ts_ms")), _f(r.get("realized_net_pnl_usdc"))
            if ts is None or pnl is None:
                continue
            out.append({"ts_ms": int(ts), "realise": pnl,
                        "coin": str(r.get("coin") or ""),
                        "strategie": str(r.get("strategie") or "carry")})
    except OSError:
        return []
    return sorted(out, key=lambda e: e["ts_ms"])


def construire(root: str | Path = ".", *, mode: str = "LIVE",
               capital_initial: float = CAPITAL_INITIAL_DEFAUT,
               funding_regle_usd: float = 0.0, now_ms: int | None = None,
               max_points: int = 600) -> dict[str, Any]:
    """La courbe complète : `{points, plate, base, capital_initial, ...}`.

    Chaque point : `{t, equity, pnl, evenement}`. Le premier est le capital de départ ; chaque
    `CLOSE` en ajoute un ; le dernier porte le funding réglé courant.
    """
    import time as _t
    now = int(now_ms if now_ms is not None else _t.time() * 1000)
    cap = float(capital_initial) if _f(capital_initial) and capital_initial > 0 \
        else CAPITAL_INITIAL_DEFAUT
    evts = evenements_realises(root, mode=mode)

    t0 = evts[0]["ts_ms"] - 60_000 if evts else now - 3_600_000
    points: list[dict[str, Any]] = [{"t": t0, "equity": round(cap, 6), "pnl": 0.0,
                                     "evenement": "DEPART"}]
    cumul = 0.0
    for e in evts:
        cumul += e["realise"]
        points.append({"t": e["ts_ms"], "equity": round(cap + cumul, 6),
                       "pnl": round(cumul, 6),
                       "evenement": "%s %s" % (e["strategie"].upper(), e["coin"])})
    # le point COURANT : réalisé cumulé + funding réellement réglé (jamais l'estimation).
    fr = _f(funding_regle_usd) or 0.0
    points.append({"t": now, "equity": round(cap + cumul + fr, 6),
                   "pnl": round(cumul + fr, 6), "evenement": "MAINTENANT",
                   "inclut_funding_courant": True})

    if len(points) > int(max_points) > 2:
        # on garde TOUJOURS le départ et le point courant : sans eux, la base et le live
        # disparaissent, et c'est le graphe qui se met à mentir sur son propre cadre.
        garde = int(max_points) - 2
        points = [points[0]] + points[-(garde + 1):]

    eqs = [p["equity"] for p in points]
    amplitude = max(eqs) - min(eqs)
    return {
        "points": points,
        "count": len(points),
        "base": round(cap, 6),
        "capital_initial": round(cap, 6),
        "realise_cumule": round(cumul, 6),
        "funding_regle_usd": round(fr, 6),
        "amplitude_usd": round(amplitude, 6),
        # `plate` = rien ne s'est jamais passé. L'écran doit le DIRE, pas dessiner du bruit.
        "plate": len(evts) == 0 and abs(fr) < 1e-9,
        "evenements": len(evts),
        "assez_de_points": len(points) >= POINTS_MIN_POUR_UNE_FORME,
        "source": "ledger carry (CLOSE horodatés) + funding RÉGLÉ courant",
        "mode": mode, "real_execution": False,
    }


def fusionner_copy(courbe: dict[str, Any],
                   points_copy: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Ajoute le PnL de la pile **copy** à la courbe du ledger, si tant est qu'il bouge.

    La copy est éteinte depuis le 11/07 : ses 600 points persistés valent tous `pnl = 0,0`.
    Plutôt que de la supprimer (elle pourrait redémarrer) ou de la laisser écraser la courbe
    (c'est le bug d'origine), on la **mesure** : amplitude nulle -> on ne fusionne rien et on
    le déclare. Amplitude non nulle -> son PnL s'ajoute par escalier (dernière valeur connue
    à gauche de chaque instant), car un PnL copy n'est pas interpolable entre deux mesures.

    Dans les deux cas `courbe["sources"]` dit exactement ce que la courbe contient. Une courbe
    qui ne sait pas énumérer ses propres sources finira par en oublier une — c'est déjà arrivé.
    """
    pts_c = [p for p in (points_copy or [])
             if isinstance(p, dict) and _f(p.get("t")) is not None
             and _f(p.get("pnl")) is not None]
    sortie = dict(courbe)
    sources = ["ledger carry/arbitrage (CLOSE horodatés)", "funding réglé courant"]
    if not pts_c:
        sortie["sources"] = sources
        sortie["copy_fusionnee"] = False
        sortie["copy_motif"] = "aucun point copy"
        return sortie
    pnls = [float(p["pnl"]) for p in pts_c]
    if max(pnls) - min(pnls) < 1e-9 and abs(pnls[-1]) < 1e-9:
        sortie["sources"] = sources
        sortie["copy_fusionnee"] = False
        sortie["copy_motif"] = ("pile copy à plat sur %d points (PnL identiquement 0) : "
                                "rien à fusionner" % len(pts_c))
        return sortie
    pts_c.sort(key=lambda p: float(p["t"]))
    ts = [float(p["t"]) for p in pts_c]
    fusion: list[dict[str, Any]] = []
    j = 0
    for p in courbe.get("points") or []:
        t = float(p.get("t") or 0)
        while j + 1 < len(ts) and ts[j + 1] <= t:
            j += 1
        # escalier : avant la première mesure copy, sa contribution est 0, pas sa 1ère valeur.
        add = float(pts_c[j]["pnl"]) if ts[j] <= t else 0.0
        q = dict(p)
        q["equity"] = round(float(q.get("equity") or 0.0) + add, 6)
        q["pnl"] = round(float(q.get("pnl") or 0.0) + add, 6)
        q["copy_pnl"] = round(add, 6)
        fusion.append(q)
    sortie["points"] = fusion
    eqs = [p["equity"] for p in fusion] or [0.0]
    sortie["amplitude_usd"] = round(max(eqs) - min(eqs), 6)
    sortie["plate"] = False
    sortie["sources"] = sources + ["pile copy (%d points)" % len(pts_c)]
    sortie["copy_fusionnee"] = True
    sortie["copy_motif"] = ""
    return sortie


def bornes_affichage(points: list[dict[str, Any]], *,
                     marge_frac: float = 0.16) -> dict[str, Any]:
    """Les bornes Y du tracé, avec le cas dégénéré traité EXPLICITEMENT.

    Une amplitude nulle donnait `rng = 0` puis une division par zéro déguisée en `|| 1` :
    tous les points s'écrasaient sur une ligne, et le moindre point vivant produisait une
    falaise. Ici : amplitude nulle -> fenêtre symétrique autour de la valeur, et `degenere`
    est retourné pour que l'écran puisse le dire.
    """
    eqs = [p.get("equity") for p in (points or []) if _f(p.get("equity")) is not None]
    if not eqs:
        return {"lo": 0.0, "hi": 1.0, "degenere": True, "motif": "aucun point"}
    lo, hi = min(eqs), max(eqs)
    if hi - lo < 1e-9:
        # fenêtre de ±0,5 % autour de la valeur : la ligne est plate ET visible au centre.
        demi = max(abs(lo) * 0.005, 0.01)
        return {"lo": round(lo - demi, 6), "hi": round(hi + demi, 6), "degenere": True,
                "motif": "amplitude nulle : rien n'a bougé"}
    marge = (hi - lo) * float(marge_frac)
    return {"lo": round(lo - marge, 6), "hi": round(hi + marge, 6), "degenere": False,
            "motif": ""}


__all__ = ["CAPITAL_INITIAL_DEFAUT", "POINTS_MIN_POUR_UNE_FORME", "evenements_realises",
           "construire", "bornes_affichage"]
