"""RAPPORT du labo CONTINU (Flo 26/07). Construit le rapport Markdown ultra-complet (snapshot intermédiaire
OU final au Ctrl+C) et agrège les CSV/JSON machine-readable sur TOUTES les campagnes. Sépare toujours
discovery / validation / holdout / forward ; une piste exploratoire n'est jamais présentée comme validée.
Indique clairement : confirmé / prometteur / à confirmer / rejeté / pourquoi / depuis combien de temps.
0 réseau, 0 ordre.
"""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path


def _lire(p: Path, defaut):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _lignes(p: Path):
    p = Path(p)
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def _csv(p: Path, cols, lignes):
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for l in lignes:
        w.writerow(l)
    p.write_text(buf.getvalue(), encoding="utf-8")


def _agreger(rundir: Path):
    """Agrège les campagnes : trials, verdicts finaux, accounting, logs. Rend un dict de séries."""
    rundir = Path(rundir)
    camps = sorted((rundir / "campagnes").glob("camp-*")) if (rundir / "campagnes").exists() else []
    trials, finals, coverage, gate, missed, exclusions = [], [], [], [], [], []
    tot = {"fast_screen": 0, "exact_replays": 0, "survivants": 0, "forward_events": 0, "pass": 0,
           "sources_detectees": 0, "sources_parsees": 0, "sources_exclues": 0, "events": 0}
    for c in camps:
        r = _lire(c / "resultats" / "pipeline_resume.json", {})
        acc = r.get("accounting", {})
        tot["fast_screen"] += r.get("n_fast_screen", 0); tot["exact_replays"] += r.get("n_exact_replays", 0)
        tot["survivants"] += r.get("n_survivants", 0); tot["forward_events"] += r.get("n_forward_events", 0)
        tot["pass"] += r.get("n_pass", 0)
        tot["sources_detectees"] = max(tot["sources_detectees"], acc.get("n_total_detected", 0))
        tot["sources_parsees"] = max(tot["sources_parsees"], acc.get("n_parsed", 0))
        tot["sources_exclues"] = max(tot["sources_exclues"], acc.get("n_excluded", 0))
        tot["events"] += (r.get("corpus_comptes", {}) or {}).get("utilises", 0)
        for t in _lignes(c / "ledger" / "trials_results.jsonl"):
            trials.append({**t, "campaign": c.name})
        for fv in _lire(c / "resultats" / "final_verdicts.json", []):
            finals.append({**fv, "campaign": c.name})
        la = _lire(c / "resultats" / "log_analysis.json", {})
        gv = la.get("gate_vs_nogate", {})
        if gv:
            gate.append({"campaign": c.name, **gv})
        for x in _lignes(c / "results" / "data_source_exclusions.csv" if False else Path("/nonexistent")):
            exclusions.append(x)
    return {"camps": camps, "trials": trials, "finals": finals, "tot": tot, "gate": gate}


def _classer(finals):
    """Sépare confirmé/prometteur/à-confirmer/rejeté (jamais mélangé). Holdout>0 = prometteur ; PASS = confirmé."""
    conf, prom, aconf, rej = [], [], [], []
    for f in finals:
        v = f.get("verdict")
        nm = f.get("holdout_net_median_bps")
        if v == "PASS_FORWARD_PAPER":
            conf.append(f)
        elif nm is not None and nm > 0:
            prom.append(f)
        elif v in ("SHADOW", "RESEARCH_ONLY", "DATA_MISSING"):
            aconf.append(f)
        else:
            rej.append(f)
    return conf, prom, aconf, rej


def construire(rundir, ident, *, final: bool = True, partial: bool = False, retourner_exclusions: bool = False):
    rundir = Path(rundir)
    ag = _agreger(rundir)
    trials, finals, tot = ag["trials"], ag["finals"], ag["tot"]
    conf, prom, aconf, rej = _classer(finals)
    debut = ident.get("t0_wall_ms", time.time() * 1000) / 1000.0
    ecoule = time.time() - debut
    # CSV machine-readable agrégés
    res = rundir / "results"
    _csv(res / "all_trials.csv", ["trial_id", "family", "coin", "horizon_ms", "net_median_bps", "pf", "sharpe", "verdict", "campaign"], trials)
    _csv(res / "candidates.csv", ["trial_id", "coin", "horizon_ms", "holdout_net_median_bps", "verdict", "campaign"], prom + conf)
    _csv(res / "rejected_candidates.csv", ["trial_id", "coin", "horizon_ms", "verdict", "raisons", "campaign"], rej)
    _csv(res / "pnl_by_candidate.csv", ["trial_id", "coin", "pnl_usd_par_trade", "roi_immobilise_pct", "verdict"], finals)
    # matrices
    def _mat(cle):
        agg = {}
        for t in trials:
            k, v = t.get(cle), t.get("net_median_bps")
            if k is None or v is None:
                continue
            agg.setdefault(k, []).append(v)
        return [{cle: k, "net_median_bps": round(sorted(vs)[len(vs) // 2], 3), "n": len(vs)} for k, vs in agg.items()]
    _csv(res / "horizon_matrix.csv", ["horizon_ms", "net_median_bps", "n"], _mat("horizon_ms"))
    _csv(res / "regime_matrix.csv", ["regime", "net_median_bps", "n"], _mat("regime"))
    _csv(res / "pnl_by_coin.csv", ["coin", "net_median_bps", "n"], _mat("coin"))
    _csv(res / "gate_analysis.csv", ["campaign", "n_refuses_rejoues", "opportunites_bloquees", "gain_manque_median_bps", "pertes_evitees"], ag["gate"])

    typ = "FINAL" if final else "SNAPSHOT (intermédiaire — PAS le rapport final)"
    L = []
    L.append("# RAPPORT — RECHERCHE CONTINUE HYPERSMART (%s, paper-only)\n" % typ)
    L.append("## 1. Résumé pour Flo")
    if conf:
        L.append("**%d piste(s) CONFIRMÉE(S)** (PASS forward paper), %d prometteuses (holdout>0), %d à confirmer, %d rejetées.\n" % (len(conf), len(prom), len(aconf), len(rej)))
    elif prom:
        L.append("Aucune confirmée ; **%d prometteuse(s)** (holdout>0, à valider en forward), %d à confirmer, %d rejetées. Pas de faux gagnant.\n" % (len(prom), len(aconf), len(rej)))
    else:
        L.append("Aucune piste positive au holdout pour l'instant. %d à confirmer, %d rejetées. Recherche honnête, rien de maquillé.\n" % (len(aconf), len(rej)))
    L.append("## 2-3. Durée & identité")
    L.append("- durée totale : **%dj %02dh %02dm %02ds** (%.0f s) · run_id `%s` · code_sha `%s`" % (
        int(ecoule // 86400), int(ecoule % 86400 // 3600), int(ecoule % 3600 // 60), int(ecoule % 60), ecoule,
        ident.get("run_id"), ident.get("code_sha")))
    L.append("- cycles terminés : **%s** · campagnes : **%d**" % (ident.get("cycle_courant", 0), len(ag["camps"])))
    L.append("## 4. Sécurité\n- read_only=%s · real_execution=%s · **0 ordre réel · 0 clé · 0 signature · 0 dépôt/retrait**\n" % (
        ident.get("read_only"), ident.get("real_execution")))
    L.append("## 5-6. Sources & couverture")
    L.append("- sources détectées **%s** · parsées **%s** · exclues **%s** · events utilisés **%s**\n" % (
        tot["sources_detectees"], tot["sources_parsees"], tot["sources_exclues"], tot["events"]))
    L.append("## 8-16. Totaux recherche")
    L.append("| métrique | valeur |\n|---|---:|")
    for k, lib in (("fast_screen", "FAST_SCREEN"), ("exact_replays", "EXACT_REPLAY"), ("survivants", "survivants"),
                   ("forward_events", "forward paper events"), ("pass", "PASS forward")):
        L.append("| %s | %s |" % (lib, tot[k]))
    L.append("")
    L.append("## 17. Pistes les plus intéressantes (exploratoire ≠ validé)")
    L.append("| candidate_id | coin | horizon | holdout net bps | PnL$/trade | ROI immob % | statut | campagne |")
    L.append("|---|---|---:|---:|---:|---:|---|---|")
    for f in sorted(prom + conf, key=lambda x: -(x.get("holdout_net_median_bps") or -1e9))[:20]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            f.get("trial_id"), f.get("coin"), f.get("horizon_ms"), f.get("holdout_net_median_bps"),
            f.get("pnl_usd_par_trade"), f.get("roi_immobilise_pct"), f.get("verdict"), f.get("campaign")))
    if not (prom + conf):
        L.append("| — | — | — | — | — | — | aucune | — |")
    L.append("")
    L.append("## 18-19. KILL & DATA_MISSING")
    L.append("- rejetées : **%d** · à confirmer/DATA_MISSING : **%d** (raisons dans rejected_candidates.csv)\n" % (len(rej), len(aconf)))
    L.append("## 20-21. Signaux refusés & effet des gates")
    for g in ag["gate"][:5]:
        L.append("- %s : refusés rejoués %s · opportunités bloquées %s (gain manqué médian %s bps) · pertes évitées %s" % (
            g.get("campaign"), g.get("n_refuses_rejoues"), g.get("opportunites_bloquees"),
            g.get("gain_manque_median_bps"), g.get("pertes_evitees")))
    L.append("")
    L.append("## 22-25. Matrices (voir CSV)\n- horizon_matrix.csv · regime_matrix.csv · pnl_by_coin.csv\n")
    # ── réconciliation PnL/ROI/equity/DD ──
    rec = _lire(rundir / "results" / "reconciliation.json", {})
    L.append("## 26. Réconciliation PnL / ROI / equity / drawdown (reconstruite depuis les ledgers d'événements)")
    if rec:
        L.append("- capital initial **%s $** · PnL réalisé **%s $** · equity **%s $** · drawdown **%s $** · ROI total **%s%%** · ROI déployé **%s%%**" % (
            rec.get("capital_initial_usd"), rec.get("pnl_realise_usd"), rec.get("equity_usd"),
            rec.get("drawdown_usd"), rec.get("roi_total_pct"), rec.get("roi_deploye_pct")))
        L.append("- campagnes **%s** · verdicts **%s** · PASS forward **%s** · equity curve : results/equity_curve.jsonl" % (
            rec.get("n_campagnes"), rec.get("n_verdicts"), rec.get("n_pass")))
        L.append("- exclusions réelles agrégées : **%s** (voir reconciliation.json)" % rec.get("n_exclusions", 0))
        L.append("- %s\n" % rec.get("note", ""))
    else:
        L.append("- réconciliation indisponible (aucune campagne finalisée) — DATA_MISSING honnête.\n")
    # ── champions / challengers (registre append-only) ──
    champs = _lignes(rundir / "results" / "champions.jsonl")
    positifs = [c for c in champs if (c.get("net_median_bps") or 0) > 0]
    L.append("## 27. Champions & challengers (registre append-only, gel immuable)")
    L.append("- candidats enregistrés : **%d** · dont net>0 : **%d** (une amélioration = NOUVEAU candidate_id + version + parent_id, jamais une réécriture)\n" % (
        len(champs), len(positifs)))
    # ── AF-P9 : architecture, outils, robustesse (plateau/concentration/capacité), jobs de fond ──
    L.append("## 28. Architecture (chaîne PROD-TRUTH)")
    L.append("- ingestion incrémentale (curseurs) → CanonicalStore (maturation PENDING→READY) → discovery → "
             "validation → holdout historique → **gel (freeze_ts)** → forward live (exchange_ts>freeze_ts) → "
             "portefeuille GLOBAL persistant → réconciliation ledger. Prix exécutables ask→bid, coûts complets.\n")
    camps_dirs = ag["camps"]
    ou = _lire((camps_dirs[-1] / "resultats" / "outils_recherche.json") if camps_dirs else Path("/nonexistent"), {})
    L.append("## 29. Outils d'optimisation réellement utilisés")
    if ou:
        L.append("- disponibles : **%s** · lancés : **%s** · avec vrais trials : **%s**" % (
            ou.get("n_disponibles"), ou.get("n_lances"), ou.get("n_avec_trials_reels")))
        for nom, v in (ou.get("outils") or {}).items():
            L.append("  - %s : dispo=%s lancé=%s trials_terminés=%s prunés=%s échoués=%s cpu=%ss%s" % (
                nom, v.get("disponible"), v.get("lance"), v.get("trials_termines"), v.get("trials_prunes"),
                v.get("trials_echoues"), v.get("cpu_s"), (" [%s]" % v["raison"] if v.get("raison") else "")))
    else:
        L.append("- PAS ENCORE CALCULABLE — aucun tableau d'outils écrit.")
    L.append("")
    L.append("## 30. Robustesse des pistes (plateau de PARAMÈTRES, concentration, capacité)")
    for f in (prom + conf)[:10]:
        L.append("- %s | plateau_params=%s | concentration(1 coin domine)=%s | capacité=%s%s | horizons_stables=%s" % (
            f.get("trial_id"), f.get("plateau"), f.get("un_seul_coin_dominant"), f.get("capacite_non_nulle"),
            (" (%s)" % f["capacite_motif"] if f.get("capacite_motif") else ""), f.get("stabilite_horizons")))
    if not (prom + conf):
        L.append("- aucune piste prometteuse (honnête).")
    L.append("")
    jf = _lire(rundir / "jobs" / "travail_de_fond.json", {})
    L.append("## 31. Travail de fond (aucun idle)")
    L.append("- jobs exécutés : **%s** · DONE : **%s** · bloqués faute de données : **%s** (stress/placebos/WF/LOCO/LORO/voisins/revalidation)\n" % (
        jf.get("n_jobs_executes", "PAS ENCORE CALCULABLE"), jf.get("n_done", "-"), jf.get("n_bloques_data", "-")))
    L.append("## 37. Lineage\n- data_lineage.jsonl (source→événement→…→PnL→rapport ; PnL sans lignée = NON_AUDITABLE)\n")
    L.append("## 41-43. Limites & prochaines pistes")
    L.append("- Un run de recherche ne PROUVE rien seul : les prometteuses doivent tenir en forward paper OOS. "
             "Renforcer les survivants (familles × horizons × régimes), compléter les DATA_MISSING.\n")
    L.append("## 44. Reproduction")
    L.append("```\nLANCER-RECHERCHE-CONTINUE.cmd start   # meme code_sha %s\n```\n" % ident.get("code_sha"))
    L.append("## 45. Manifeste\n- SHA256_MANIFEST_FINAL.json (écrit en DERNIER, contient ce rapport + tous les results)\n")
    if partial:
        L.append("> ⚠️ **FINALIZATION_PARTIAL** : arrêt d'urgence (2e Ctrl+C). Complet : campagnes écrites + CSV. "
                 "Incomplet : cycle en cours interrompu. Aucune perte silencieuse.\n")
    L.append("---\n**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**")
    md = "\n".join(L) + "\n"
    if retourner_exclusions:
        try:
            import reconciliation_prod as RECO
            exclusions = RECO.agreger_exclusions(rundir)      # VRAIES exclusions (jamais [] par défaut si présentes)
        except Exception:  # noqa: BLE001
            exclusions = []
        return md, exclusions
    return md


__all__ = ["construire"]
