"""LEÇONS DU LEDGER — la boucle « perte → leçon → règle », rendue AUTOMATIQUE et déterministe.

ORIGINE (20/07) : article « Loop Engineering » de Roan (@RohOnChain) analysé sur demande de
Flo. Sa meilleure idée : *chaque perte écrit une leçon, chaque leçon devient une règle, le
fichier de règles devient de la connaissance institutionnelle*. Chez nous cette boucle
existait... à la main : c'est l'agent qui lisait le ledger, nommait la cause, écrivait le
correctif et le test. Ce module automatise le PREMIER maillon — LA DÉTECTION — sans jamais
laisser un LLM inventer une règle :

  * chaque perte du ledger est classée contre le REGISTRE des causes connues ;
  * une perte dont la cause a été RÉPARÉE (commit daté) qui revient APRÈS le correctif
    = RÉGRESSION — alarme rouge ;
  * une perte qui ne correspond à AUCUNE cause connue = INEXPLIQUÉE — alarme rouge :
    c'est le signal qu'une autopsie humaine est due (la leçon n'existe pas encore).

Différence assumée avec l'article : ses leçons vivent en markdown consommé par un agent ;
les nôtres deviennent du CODE (portes + tests-cliquets). Un markdown peut être ignoré par
le prochain run — un test rouge, jamais. Ce module ne remplace pas l'autopsie : il garantit
qu'aucune perte ne passe une nuit sans être ou EXPLIQUÉE ou SIGNALÉE.

Lecture seule. 0 ordre réel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEDGER_RELPATH = Path("runtime") / "data" / "carry_paper_ledger.jsonl"

#: LE REGISTRE. Chaque motif de fermeture PERDANTE que ce projet a déjà payé, nommé, et
#: traité. `statut` : ATTENDU (économie normale de la stratégie — une perte ici s'explique) ou
#: REPARE (cause éteinte par un commit daté — une perte ici APRÈS `repare_ts_ms` = RÉGRESSION).
#: Les ts sont en ms epoch. Ajouter une entrée = avoir écrit l'autopsie ET le correctif.
CAUSES_CONNUES: dict[str, dict[str, Any]] = {
    # -- économie normale (pertes possibles, bornées, comprises) --------------------------
    "SORTIE_LIQUIDATION": {
        "statut": "ATTENDU",
        "note": "le tampon a cede sur un mouvement extreme : c'est LE risque du carry, "
                "borne par le levier risk-parity (1,5x) et le verrou pire-hausse."},
    "FUNDING_NON_RENTABLE": {
        "statut": "ATTENDU",
        "note": "hemorragie (<= -0,5 bps/h) ou negatif persistant : sortir coute, rester "
                "coute plus (A6, 6e28f33)."},
    "SORTIE_AGE": {
        "statut": "ATTENDU",
        "note": "14 j sans revalidation -> fermeture volontaire anti-zombie. Une perte ici "
                "doit rester rare : le cliquet BE<=0,7xAGE l'empeche par construction."},
    "ROTATION_HORS_TOP_SLOTS": {
        "statut": "ATTENDU",
        "note": "A7 : remplace par un meilleur net, surplus > cout de rotation exige."},
    # -- causes REPAREES (une perte ici apres la date = REGRESSION, alarme) ---------------
    "COIN_PLUS_DANS_SHORTLIST": {
        "statut": "REPARE", "repare_ts_ms": 1784460540000,   # 19/07 13:29
        "commit": "586b466+a7456f4",
        "note": "le churn shortlist (-5,07 $) : sorties non urgentes gatees par "
                "l'amortissement (A1-A5)."},
    "DONNEE_ABSENTE_PROLONGEE": {
        "statut": "REPARE", "repare_ts_ms": 1784546700000,   # 20/07 ~13:25 (e82dd4a+b6debb2)
        "commit": "e82dd4a+b6debb2",
        "note": "fermetures famine/rate-de-bougies : hors-shortlist gate par amortissement "
                "quand la donnee est vivante + cache pire-hausse 24 h. Le vrai blackout "
                "(0 mesure) reste une fermeture legitime -> demi-alarme seulement."},
    "BASE_CONVERGEE_PREMIUM_CAPTURE": {
        "statut": "REPARE", "repare_ts_ms": 1784546700000,   # 20/07 (e82dd4a)
        "commit": "e82dd4a",
        "note": "une 'capture' ne se verrouille plus a perte (A5 x A4 : pnl_realise > 0 "
                "exige). Une perte ici apres la date = la porte a saute."},
    # -- ARBITRAGE de dislocation (ajoute le 22/07 : les MKR '-0,04/-0,08 $' etaient marques
    #    INEXPLIQUEES faute d'entree ici, alors que la LECON EXISTE, loi `arb_ecart_fige`). ----
    "ARB_AGE_MAX_SANS_CONVERGENCE": {
        "statut": "ATTENDU",
        "note": "l'ecart n'a pas converge avant l'age max -> on coupe, on paie le cout (loi "
                "arb_dislocation_cout_all_in : 16 bps A/R). Cas MKR : ecart FIGE a 71,44 bps "
                "(sigma 0,0000 sur 208 obs, loi arb_ecart_fige) -> ce qui ne bouge pas n'est "
                "pas capturable. La porte de vivacite (21/07) refuse desormais ce coin AVANT "
                "l'ouverture : une perte ARB_AGE_MAX sur un ecart FIGE apres le 21/07 = "
                "REGRESSION (la porte a saute)."},
    "ARB_STOP_ECART_AGGRAVE": {
        "statut": "ATTENDU",
        "note": "l'ecart s'est ELARGI dans notre dos (>= entree + 25 bps) -> on coupe pour ne "
                "pas parier une dislocation qui diverge (jambe Binance conceptuelle, risque "
                "reel). Perte bornee par le stop, voulue."},
    "ARB_CONVERGENCE_CAPTUREE": {
        "statut": "ATTENDU",
        "note": "l'ecart a converge dans notre sens et on a capture au-dessus du cout all-in "
                "-> PnL positif. C'est le seul cas d'arbitrage qui doit finir en vert."},
}

VERDICT_EXPLIQUEE = "EXPLIQUEE"
VERDICT_REGRESSION = "REGRESSION_CAUSE_REPAREE"
VERDICT_INEXPLIQUEE = "INEXPLIQUEE_AUTOPSIE_REQUISE"


def classer_perte(motif: str, ts_ms: int) -> tuple[str, str]:
    """(verdict, note). Une perte est EXPLIQUÉE, une RÉGRESSION, ou INEXPLIQUÉE — jamais muette."""
    entree = CAUSES_CONNUES.get(str(motif))
    if entree is None:
        return (VERDICT_INEXPLIQUEE,
                "motif %r absent du registre : la leçon n'existe pas encore — autopsie due" % motif)
    if entree["statut"] == "REPARE" and int(ts_ms) >= int(entree.get("repare_ts_ms") or 0):
        return (VERDICT_REGRESSION,
                "cause reparee (%s) qui REVIENT apres le correctif : %s"
                % (entree.get("commit"), entree.get("note", "")))
    return (VERDICT_EXPLIQUEE, entree.get("note", ""))


def lecons(root: str | Path = ".", *, depuis_ms: int = 0) -> dict[str, Any]:
    """Toutes les fermetures PERDANTES depuis `depuis_ms`, classées. Ne lève jamais."""
    out: dict[str, Any] = {"expliquees": [], "regressions": [], "inexpliquees": [],
                           "pertes_totales_usdc": 0.0}
    try:
        lignes = (Path(root) / LEDGER_RELPATH).read_text(
            encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for l in lignes:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("kind") != "CLOSE":
            continue
        pnl = float(r.get("realized_net_pnl_usdc") or 0.0)
        ts = int(r.get("ts_ms") or 0)
        if pnl >= 0 or ts < depuis_ms:
            continue                                   # les gains n'ont pas besoin d'excuse
        verdict, note = classer_perte(str(r.get("reason")), ts)
        item = {"coin": r.get("coin"), "ts_ms": ts, "pnl_usdc": round(pnl, 6),
                "motif": r.get("reason"), "verdict": verdict, "note": note}
        out["pertes_totales_usdc"] = round(out["pertes_totales_usdc"] + pnl, 6)
        cle = {VERDICT_EXPLIQUEE: "expliquees", VERDICT_REGRESSION: "regressions",
               VERDICT_INEXPLIQUEE: "inexpliquees"}[verdict]
        out[cle].append(item)
    return out


def resume_markdown(root: str | Path = ".", *, depuis_ms: int = 0) -> list[str]:
    """Le bloc pour le rapport quotidien : silencieux quand tout va bien, ROUGE sinon."""
    r = lecons(root, depuis_ms=depuis_ms)
    out = ["## 6. Leçons du ledger — aucune perte sans explication", ""]
    n = len(r["expliquees"]) + len(r["regressions"]) + len(r["inexpliquees"])
    if n == 0:
        out.append("Aucune perte sur la fenêtre. (La boucle perte→leçon n'a rien à dire.)")
        return out
    out.append("%d perte(s), %+.4f $ au total :" % (n, r["pertes_totales_usdc"]))
    for it in r["regressions"]:
        out.append("- 🔴 **RÉGRESSION** %s %+.4f $ `%s` — %s"
                   % (it["coin"], it["pnl_usdc"], it["motif"], it["note"]))
    for it in r["inexpliquees"]:
        out.append("- 🔴 **INEXPLIQUÉE** %s %+.4f $ `%s` — %s"
                   % (it["coin"], it["pnl_usdc"], it["motif"], it["note"]))
    for it in r["expliquees"]:
        out.append("- ✔ %s %+.4f $ `%s` (attendu : %s)"
                   % (it["coin"], it["pnl_usdc"], it["motif"], it["note"][:70]))
    return out


__all__ = ["CAUSES_CONNUES", "VERDICT_EXPLIQUEE", "VERDICT_REGRESSION", "VERDICT_INEXPLIQUEE",
           "classer_perte", "lecons", "resume_markdown"]
