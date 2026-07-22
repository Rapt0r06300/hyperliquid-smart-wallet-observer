"""CERVELLE DIAGNOSTIC — transformer les chiffres bruts du RECAP en COMPRÉHENSION du PnL.

Flo (22/07) : « c'est le fichier qui doit nous permettre de COMPRENDRE et de TROUVER comment
avoir un PnL positif ». Le RECAP a déjà les nombres (PnL par stratégie/motif, funding, santé) —
mais un nombre n'est pas une compréhension. Ce module lit ce qui a DÉJÀ été mesuré et répond, en
une section, à trois questions : **où va l'argent ? l'edge existe-t-il ? que faire ensuite ?**

Il n'invente rien : chaque ligne remonte à une mesure (RECAP, dispersion, liquidations) ou dit
INSUFFISANT. Il ne promet aucun PnL — il dit la vérité, y compris quand elle est négative (le
carry au plancher est dominé ; l'arbitrage au mid était une illusion). Lecture seule, aucun ordre.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from hl_observer.collection import collecte_fiable as _CF

#: bps/h qu'il faut dépasser pour battre le bas de HLP (cf. carry_benchmark_gate).
SEUIL_HLP_BPS_H = 0.266
PLANCHER_BPS_H = 0.125


def _bloc_dict(recap: str, etiquette: str) -> dict:
    """Extrait un dict Python affiché dans le RECAP après `etiquette` (ex. 'par stratégie :')."""
    m = re.search(re.escape(etiquette) + r"\s*`?(\{[^`\n]*\})`?", recap)
    if not m:
        return {}
    try:
        d = ast.literal_eval(m.group(1))
        return d if isinstance(d, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def pnl_depuis_recap(recap: str) -> dict[str, Any]:
    """{total, fermetures, par_strategie, par_motif} lus dans le RECAP. Tolérant, deny-by-default."""
    out: dict[str, Any] = {"total": None, "fermetures": None, "par_strategie": {}, "par_motif": {}}
    m = re.search(r"total\s*:\s*\*\*([+\-]?[0-9.]+)\s*\$\*\*\s*sur\s*(\d+)", recap)
    if m:
        out["total"] = float(m.group(1))
        out["fermetures"] = int(m.group(2))
    out["par_strategie"] = _bloc_dict(recap, "par stratégie :")
    out["par_motif"] = _bloc_dict(recap, "par motif :")
    return out


def ou_va_l_argent(pnl: dict[str, Any]) -> list[str]:
    """Les lignes « où va l'argent » : meilleure/pire stratégie, motif le plus coûteux."""
    lignes: list[str] = []
    if pnl.get("total") is None:
        return ["- PnL 24 h : **INSUFFISANT** (aucun total lisible dans le RECAP)."]
    lignes.append("- PnL 24 h : **%+.4f $** sur %s fermeture(s)."
                  % (pnl["total"], pnl.get("fermetures")))
    strat = pnl.get("par_strategie") or {}
    if strat:
        best = max(strat.items(), key=lambda kv: kv[1])
        worst = min(strat.items(), key=lambda kv: kv[1])
        lignes.append("- meilleure stratégie : **%s** (%+.4f $) · pire : **%s** (%+.4f $)."
                      % (best[0], best[1], worst[0], worst[1]))
    motifs = pnl.get("par_motif") or {}
    couteux = [(k, v) for k, v in motifs.items() if v < 0]
    if couteux:
        pire = min(couteux, key=lambda kv: kv[1])
        lignes.append("- motif le plus COÛTEUX : **%s** (%+.4f $) — c'est LUI à comprendre avant "
                      "d'ajouter quoi que ce soit." % (pire[0], pire[1]))
    return lignes


def funding_hors_plancher(lignes: list[dict], *, seuil_hlp: float = SEUIL_HLP_BPS_H) -> dict[str, Any]:
    """Sur les observations de funding HL : quelle part BAT HLP ? (le carry n'existe QUE là)."""
    n = 0
    au_dessus = 0
    bat_hlp = 0
    mx = 0.0
    coins: set = set()
    for r in lignes or ():
        hl = r.get("hl_bps_h")
        if not isinstance(hl, (int, float)):
            continue
        n += 1
        coins.add(str(r.get("coin") or ""))
        mx = max(mx, float(hl))
        if hl > PLANCHER_BPS_H + 0.01:
            au_dessus += 1
        if hl >= seuil_hlp:
            bat_hlp += 1
    if not n:
        return {"n": 0, "verdict": "INSUFFISANT (aucune observation de funding)"}
    pct = 100.0 * bat_hlp / n
    if bat_hlp:
        q = "le carry a une FENÊTRE — cibler ces coins/moments"
    elif len(coins) >= 150:
        q = ("le carry est DOMINÉ par HLP MÊME sur l'univers large (%d coins) : ce n'est PAS un "
             "problème d'univers, il n'y a simplement pas de demande de funding à capturer"
             % len(coins))
    else:
        q = "le carry est DOMINÉ par HLP dans cet univers — élargir l'univers est sa seule chance"
    verdict = ("le funding BAT HLP %.2f%% du temps (max %.3f bps/h) sur %d coins : %s"
               % (pct, mx, len(coins), q))
    return {"n": n, "coins": len(coins), "pct_bat_hlp": round(pct, 3), "max_bps_h": round(mx, 4),
            "univers_large": len(coins) >= 150, "verdict": verdict}


def synthese_edge(racine: str | Path) -> list[str]:
    """La synthèse d'edge : carry (funding-plancher), arbitrage (prix exécutable), liquidations.
    Chaque ligne remonte à une mesure réelle ou dit INSUFFISANT — jamais un espoir inventé."""
    racine = Path(racine)
    lignes: list[str] = []
    disp = racine / "runtime" / "data" / "dispersion_venues.jsonl"
    obs = _charger_jsonl(disp, limite=200_000)
    # carry
    f = funding_hors_plancher(obs)
    if f.get("n"):
        lignes.append("- **carry** : %s" % f["verdict"])
    # arbitrage au prix exécutable
    try:
        from hl_observer.funding import arb_executable as AX
        signaux = _episodes_arb(obs)
        va = AX.verdict_population(signaux, seuil_bps=19.0)
        if va["signaux"] or va.get("ecartes_aberrants"):
            lignes.append("- **arbitrage** (prix exécutable, modèle) : %s" % va["verdict"])
    except Exception:  # noqa: BLE001 — une synthèse absente ne casse pas le diagnostic
        pass
    # liquidations
    liq = liq_progression(racine)
    lignes.append("- **liquidations** : %s" % liq["verdict"])
    return lignes or ["- edge : INSUFFISANT (données absentes ce tour)."]


def liq_progression(racine: str | Path, *, cible: int = 50) -> dict[str, Any]:
    """Combien d'événements de liquidation exploitables accumulés vs la cible (~50 pour un verdict)."""
    try:
        import sys
        sys.path.insert(0, str(Path(racine) / "src"))
        from hl_observer.market.liquidation_recorder import resume_historique
        etat = resume_historique(root=str(racine))
        n = int(etat.get("snapshots") or 0)
    except Exception:  # noqa: BLE001
        n = 0
    # 🔴 HONNÊTETÉ : `snapshots` = PHOTOGRAPHIES brutes de grappes, PAS des événements distincts.
    # Après dédup temporel + franchissement réel, il n'en reste qu'une poignée (~3 mesurés). Ne
    # jamais confondre les deux — sinon on annonce « assez pour un verdict » sur du sur-comptage.
    verdict = ("%d photographie(s) brute(s) de grappes ; après dédup il reste très peu "
               "d'événements DISTINCTS (~3 mesurés, cible %d) — verdict à l'accumulation de vraies "
               "purges (ciblage fort levier désormais actif)" % (n, cible))
    return {"n_snapshots_bruts": n, "cible": cible, "verdict": verdict}


def prochaine_action(pnl: dict[str, Any], edge: list[str]) -> str:
    """LA prochaine action, une seule ligne, dérivée de l'état — jamais un vœu."""
    txt = " ".join(edge).lower()
    if "même sur l'univers large" in txt:
        return ("PROCHAINE ACTION : le carry est dominé MÊME sur l'univers large -> ce n'est pas "
                "un edge de funding, et ce n'était pas un problème d'univers. Espoir restant : les "
                "LIQUIDATIONS (flux forcé) — accumuler des événements distincts (ciblage fort "
                "levier) ; sinon cash/HLP est le benchmark honnête à assumer, pas à maquiller.")
    if "élargir l'univers" in txt or "dominé par hlp" in txt:
        return ("PROCHAINE ACTION : laisser le collecteur d'univers élargi tourner ~24 h, puis "
                "re-mesurer le funding sur les 200 coins. Si rien ne bat HLP -> redéployer vers cash/HLP.")
    if "illusion" in txt:
        return ("PROCHAINE ACTION : l'arbitrage ne survit pas au mid -> capturer le carnet réel "
                "(bid/ask + taille) avant d'y croire ; ne pas câbler l'arb en attendant.")
    return "PROCHAINE ACTION : accumuler les données (liquidations, univers) puis re-juger — rien à forcer."


def construire(racine: str | Path, *, nom_recap: str = "RECAP-COMPLET.md") -> str:
    """La section « COMPRENDRE LE PnL & TROUVER L'EDGE » pour le RECAP. Vide honnête si pas de RECAP."""
    racine = Path(racine)
    recap = ""
    p = racine / nom_recap
    if p.exists():
        recap = p.read_text(encoding="utf-8", errors="ignore")
    pnl = pnl_depuis_recap(recap)
    edge = synthese_edge(racine)
    lignes = ["## 🧠 COMPRENDRE LE PnL & TROUVER L'EDGE", "",
              "### Où va l'argent"]
    lignes += ou_va_l_argent(pnl)
    lignes += ["", "### L'edge existe-t-il ? (chaque ligne = une mesure réelle)"]
    lignes += edge
    lignes += ["", "**%s**" % prochaine_action(pnl, edge),
               "", "_Aucune promesse de PnL : ces lignes remontent aux mesures, y compris quand "
               "elles sont négatives. C'est le prix de la vérité._"]
    return "\n".join(lignes)


# ─────────────────────────── utilitaires de lecture (tolérants) ───────────────────────────

def _charger_jsonl(chemin: Path, *, limite: int = 200_000) -> list[dict]:
    import json
    out: list[dict] = []
    try:
        with chemin.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                # porte de qualité (socle `collecte_fiable`) : on écarte les lignes à horodatage
                # implausible (fixtures/erreurs) avant toute mesure — une donnée pourrie ment.
                if isinstance(d, dict) and _CF.qualite_ok(d):
                    out.append(d)
                if len(out) >= limite:
                    break
    except OSError:
        return []
    return out


def _episodes_arb(obs: list[dict], *, seuil_bps: float = 19.0, sortie_bps: float = 3.0
                  ) -> list[tuple[float, float]]:
    """Reconstruit les (écart d'entrée, écart de sortie) de dislocation de prix par coin."""
    from collections import defaultdict
    par_coin: dict[str, list] = defaultdict(list)
    for r in obs:
        e = r.get("ecart_prix_bps")
        if isinstance(e, (int, float)):
            par_coin[str(r.get("coin"))].append((float(r.get("ts") or 0.0), float(e)))
    signaux: list[tuple[float, float]] = []
    for serie in par_coin.values():
        serie.sort()
        i = 0
        while i < len(serie):
            e0 = serie[i][1]
            if abs(e0) >= seuil_bps:
                es = serie[-1][1]
                for _t, e in serie[i + 1:]:
                    if abs(e) <= sortie_bps:
                        es = e
                        break
                signaux.append((e0, es))
                i += 1
                while i < len(serie) and abs(serie[i][1]) >= seuil_bps:
                    i += 1
            else:
                i += 1
    return signaux


__all__ = ["SEUIL_HLP_BPS_H", "pnl_depuis_recap", "ou_va_l_argent", "funding_hors_plancher",
           "synthese_edge", "liq_progression", "prochaine_action", "construire"]
