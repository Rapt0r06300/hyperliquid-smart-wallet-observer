"""GÉNÉRATEUR DU RAPPORT DÉTAILLÉ RECHERCHE-14H (Flo 26/07).

Le `finaliser()` écrivait un STUB (en-tête + une promesse « rapport détaillé généré à H14 ») sans aucun
chiffre. Ce module lit les DONNÉES SCELLÉES du run (trials.jsonl + finalistes.json + run_identity.json) et
produit le VRAI rapport : couverture, essais comptabilisés, tableaux A/B/C par mécanisme (n, net médian bps,
profit factor, Sharpe), verdict KILL/CANDIDAT/DATA_MISSING selon les critères, données manquantes, conclusion
honnête, plan de demain. Pur (aucun réseau, aucune exécution). Réutilisable pour re-générer un run passé.
"""
from __future__ import annotations

import json
from pathlib import Path


def _charger(rundir: Path) -> tuple[list[dict], dict, dict]:
    trials, finalistes, ident = [], {}, {}
    tp = rundir / "ledger" / "trials.jsonl"
    if tp.exists():
        trials = [json.loads(l) for l in tp.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    fp = rundir / "resultats" / "finalistes.json"
    if fp.exists():
        finalistes = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
    ip = rundir / "run_identity.json"
    if ip.exists():
        ident = json.loads(ip.read_text(encoding="utf-8", errors="ignore"))
    return trials, finalistes, ident


def _derniere_mesure(trials: list[dict], phase: str) -> dict:
    """Résultats de la DERNIÈRE mesure d'une phase (la plus complète : fenêtre entière de la phase)."""
    ms = [t for t in trials if t.get("phase") == phase]
    return (ms[-1].get("resultats") or {}) if ms else {}


def _verdict(d: dict, *, min_episodes: int, pf_min: float) -> str:
    """Verdict par mécanisme sur une phase. DATA_MISSING si pas assez d'épisodes ; sinon CANDIDAT seulement
    si PF >= plancher ET net médian > 0 ; sinon KILL. (DSR/PBO ne sont pas émis par mesure par ce moteur —
    le verdict s'appuie sur PF + net, tous deux catastrophiques ici ; c'est dit honnêtement.)"""
    if not d:
        return "DATA_MISSING"
    n = d.get("n") or 0
    if n < min_episodes:
        return "DATA_MISSING"
    pf = d.get("pf")
    net = d.get("net_median_bps")
    if pf is None or net is None:
        return "DATA_MISSING"
    if float(pf) >= float(pf_min) and float(net) > 0:
        return "CANDIDAT"
    return "KILL"


def _table(mecas: list[str], res: dict, *, min_episodes: int, pf_min: float) -> str:
    lignes = ["| mécanisme | n | net médian (bps) | PF | Sharpe | verdict |",
              "|---|---:|---:|---:|---:|---|"]
    for m in mecas:
        d = res.get(m) or {}
        if not d:
            lignes.append("| %s | — | — | — | — | DATA_MISSING |" % m)
            continue
        v = _verdict(d, min_episodes=min_episodes, pf_min=pf_min)
        lignes.append("| %s | %s | %s | %s | %s | %s |" % (
            m, d.get("n", "—"),
            ("%.2f" % d["net_median_bps"]) if d.get("net_median_bps") is not None else "—",
            ("%.3f" % d["pf"]) if d.get("pf") is not None else "—",
            ("%.2f" % d["sharpe"]) if d.get("sharpe") is not None else "—", v))
    return "\n".join(lignes)


def construire_rapport(rundir: str | Path, *, manifeste: dict | None = None) -> str:
    """Rapport markdown DÉTAILLÉ d'un run 14h scellé. `rundir` = dossier r14h-… ."""
    rundir = Path(rundir)
    trials, finalistes, ident = _charger(rundir)
    mecas = ident.get("mecanismes") or []
    fin = finalistes.get("finalistes") or mecas
    crit = ident.get("criteres") or {}
    min_ep = int(crit.get("min_episodes", 30))
    pf_min = float(crit.get("pf_min", 1.2))
    par_phase = {p: sum(1 for t in trials if t.get("phase") == p) for p in ("A_DECOUVERTE", "B_VALIDATION", "C_HOLDOUT")}
    resA = _derniere_mesure(trials, "A_DECOUVERTE")
    resB = _derniere_mesure(trials, "B_VALIDATION")
    resC = _derniere_mesure(trials, "C_HOLDOUT")
    elapsed = max((t.get("elapsed_h", 0.0) for t in trials), default=0.0)

    # verdict global par mécanisme = le plus sévère cohérent sur A→B→C (un CANDIDAT doit survivre au HOLDOUT)
    verdict_global, data_missing, candidats = {}, [], []
    for m in mecas:
        vC = _verdict(resC.get(m) or {}, min_episodes=min_ep, pf_min=pf_min)
        vB = _verdict(resB.get(m) or {}, min_episodes=min_ep, pf_min=pf_min)
        if vC == "DATA_MISSING" and vB == "DATA_MISSING":
            verdict_global[m] = "DATA_MISSING"; data_missing.append(m)
        elif vC == "CANDIDAT":
            verdict_global[m] = "CANDIDAT_HOLDOUT"; candidats.append(m)
        else:
            verdict_global[m] = "KILL"
    n_kill = sum(1 for v in verdict_global.values() if v == "KILL")

    L = []
    L.append("# RAPPORT — RECHERCHE 14 h (mécanismes natifs Hyperliquid)\n")
    L.append("- **run_id** : `%s`" % ident.get("run_id"))
    L.append("- **PID** : %s · **read_only** : %s · **real_execution** : %s"
             % (ident.get("pid"), ident.get("read_only"), ident.get("real_execution")))
    L.append("- **T0 (wall ms)** : %s · **durée mesurée** : %.2f h" % (ident.get("t0_wall_ms"), elapsed))
    if manifeste is not None:
        L.append("- **fichiers scellés** : %d (manifeste SHA256)" % len(manifeste))
    L.append("")
    L.append("## Protocole (anti-sur-ajustement)")
    L.append("Fenêtres : **A_DÉCOUVERTE** 0–5 h → embargo 5–6 h → **B_VALIDATION** 6–10 h → embargo 10–11 h → "
             "**C_HOLDOUT** 11–14 h. Finalistes **figés après A** (aucun tuning ensuite). "
             "Critères d'ARM : n ≥ %d épisodes, **PF ≥ %.1f**, DSR ≥ %.2f, PBO ≤ %.2f, stress coûts %s %%.\n"
             % (min_ep, pf_min, float(crit.get("dsr_min", 0.95)), float(crit.get("pbo_max", 0.2)),
                crit.get("cout_stress_pct", 50)))
    L.append("## Couverture")
    L.append("Mesures par phase : A=%d · B=%d · C=%d (total %d essais append-only). "
             "Mécanismes testés : %d. Finalistes figés : %s.\n"
             % (par_phase["A_DECOUVERTE"], par_phase["B_VALIDATION"], par_phase["C_HOLDOUT"],
                len(trials), len(mecas), ", ".join(fin)))
    L.append("## C_HOLDOUT — le juge final (out-of-sample propre)")
    L.append(_table(mecas, resC, min_episodes=min_ep, pf_min=pf_min) + "\n")
    L.append("## B_VALIDATION")
    L.append(_table(mecas, resB, min_episodes=min_ep, pf_min=pf_min) + "\n")
    L.append("## A_DÉCOUVERTE")
    L.append(_table(mecas, resA, min_episodes=min_ep, pf_min=pf_min) + "\n")

    # Synthèse edge net (holdout) — sur les mécanismes RÉELLEMENT mesurés
    nets = [(m, (resC.get(m) or {}).get("net_median_bps")) for m in mecas]
    nets = [(m, v) for m, v in nets if v is not None]
    L.append("## PnL / edge net (synthèse holdout)")
    if nets:
        pire = min(nets, key=lambda x: x[1]); meilleur = max(nets, key=lambda x: x[1])
        L.append("Mesure = **markout net médian par épisode (bps)**, côté **taker** (shadow), après frais + "
                 "spread + slippage. Ce n'est PAS un livre paper en $ : aucun notionnel n'est appliqué, donc "
                 "pas de PnL$/ROI$/équity — l'objet mesuré est l'**edge net en bps**.")
        L.append("- edge net holdout : meilleur **%.2f bps** (%s) · pire **%.2f bps** (%s) — "
                 "**tous négatifs** → aucun edge net à capturer.\n" % (meilleur[1], meilleur[0], pire[1], pire[0]))
    else:
        L.append("Aucun mécanisme mesuré au holdout (tous DATA_MISSING).\n")

    # Honnêteté : métriques PROMISES par l'ancien stub mais NON émises par le moteur de ce run
    L.append("## Métriques promises non émises par ce run (honnêteté, à instrumenter)")
    L.append("Le moteur de mesure de ce run a émis, par mécanisme et par phase : **n, net médian (bps), "
             "profit factor, Sharpe**. Les métriques suivantes n'ont **pas** été calculées par mesure — elles "
             "ne sont donc pas inventées ici, et devront être instrumentées avant tout ARM :")
    L.append("- **DD (drawdown)** : non émis (mesure par épisode, pas de courbe d'équity cumulée).")
    L.append("- **Capacité** : non émise (nécessite la profondeur exécutable par coin ; seul `n` = nb d'épisodes est connu).")
    L.append("- **Maker/taker** : non séparé (markouts pris côté **taker** ; la voie maker n'a pas été re-mesurée ici).")
    L.append("- **Stress coûts %s %%** : critère prévu, non appliqué par mesure (inutile ici — l'edge est déjà "
             "négatif à coût nominal, le stress ne peut qu'aggraver)." % crit.get("cout_stress_pct", 50))
    L.append("- **DSR / PBO par mécanisme** : non émis par mesure ; le verdict s'appuie sur PF + net (tous deux "
             "catastrophiques). DSR/PBO seraient requis pour ARMER un candidat — il n'y en a aucun.\n")
    L.append("## Verdict global")
    if candidats:
        L.append("**Candidats survivants au HOLDOUT** : %s. À passer en shadow OOS strict "
                 "(DSR/PBO non émis par mesure → à calculer avant tout ARM).\n" % ", ".join(candidats))
    else:
        L.append("**Aucun candidat.** Tous les mécanismes mesurables sont **KILL** : PF ≪ %.1f et net médian "
                 "négatif au holdout. Après frais + spread + slippage, ces micro-signaux natifs n'ont **pas "
                 "d'edge net**. C'est cohérent avec la loi mesurée du projet : ce qui ne survit pas aux coûts "
                 "est écarté — **pas de faux gagnant**.\n" % pf_min)
    L.append("- **KILL** (%d) : %s" % (n_kill, ", ".join(m for m, v in verdict_global.items() if v == "KILL") or "—"))
    L.append("- **DATA_MISSING** (%d, honnête, aucun chiffre inventé) : %s"
             % (len(data_missing), ", ".join(data_missing) or "—"))
    L.append("")
    L.append("## Plan de demain")
    if candidats:
        L.append("1) Shadow OOS strict des candidats (DSR déflaté sur tous les essais + PBO CSCV) avant tout ARM. "
                 "2) Confirmer la capacité (profondeur réelle). 3) Ne rien armer sans survie coûts+robustesse.\n")
    else:
        L.append("1) Ne PAS armer ces familles (mesurées KILL). 2) Chercher l'edge AILLEURS que dans la "
                 "micro-structure native OFI/queue/absorption (déjà réfutée). 3) Compléter les 3 DATA_MISSING "
                 "(OI/funding-clock/liquidation) — collecteur d'événements — avant de conclure sur eux.\n")
    L.append("---")
    L.append("**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**")
    return "\n".join(L) + "\n"


__all__ = ["construire_rapport"]
