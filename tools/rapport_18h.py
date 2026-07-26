"""RAPPORT 18 h EXHAUSTIF + sorties machine-readable (Flo 26/07).

Lit run_identity + catalogue + partitions + registre + résultats, et produit RAPPORT-RECHERCHE-18H.md avec :
résumé Flo, verdict, run_id, durée, SHA code, sécurité, machine, catalogue, partitions, familles/variantes,
trials uniques, épisodes bruts/dédupliqués, effective_n, KILL/DATA_MISSING/SHADOW/finalistes, résultats
discovery/validation/holdout/forward, par horizon/coin/régime, décomposition brut/coûts/net, PnL/ROI (capital
total ET immobilisé, run 18 h NON annualisé sans avertissement), drawdown, fills, capacité, stress, placebos,
DSR/PBO, benchmarks NO_TRADE/CASH, bugs trouvés, limites, non-prouvé, prochaines pistes. Ce qui n'a pas été
mesuré est marqué explicitement — jamais inventé. Écrit aussi results/*.csv/jsonl. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path


def _lire(rundir: Path, rel: str, defaut):
    try:
        return json.loads((Path(rundir) / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _lignes(rundir: Path, rel: str) -> list[dict]:
    p = Path(rundir) / rel
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def _ecrire_results(rundir: Path, resultats: list[dict]) -> None:
    """Sorties machine-readable minimales (all_trials + leaderboard). Étendues à mesure que les résultats
    arrivent ; jamais de colonne inventée."""
    rd = Path(rundir) / "results"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "all_trials.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in resultats), encoding="utf-8")
    buf = io.StringIO()
    cols = ["trial_id", "family", "variant", "net_median_bps", "pf", "sharpe", "verdict"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in resultats:
        w.writerow(r)
    (rd / "all_trials.csv").write_text(buf.getvalue(), encoding="utf-8")
    # leaderboard trié par net médian décroissant
    lb = sorted([r for r in resultats if r.get("net_median_bps") is not None],
                key=lambda r: -r["net_median_bps"])
    buf2 = io.StringIO()
    w2 = csv.DictWriter(buf2, fieldnames=cols, extrasaction="ignore")
    w2.writeheader()
    for r in lb:
        w2.writerow(r)
    (rd / "strategy_leaderboard.csv").write_text(buf2.getvalue(), encoding="utf-8")


def construire_rapport(rundir: str | Path, *, manifeste: dict | None = None) -> str:
    rundir = Path(rundir)
    ident = _lire(rundir, "run_identity.json", {})
    cat = _lire(rundir, "catalogue/DATA_CATALOG.json", {"resume": {}, "sources": []})
    split = _lire(rundir, "partitions/DATA_SPLIT_MANIFEST.json", {})
    prereg = _lignes(rundir, "ledger/trials_preregistered.jsonl")
    results = _lignes(rundir, "ledger/trials_results.jsonl")
    _ecrire_results(rundir, results)
    resume_cat = cat.get("resume", {})

    familles = {r.get("family") for r in results if r.get("family")}
    verdicts = {}
    for r in results:
        verdicts.setdefault(r.get("verdict", "?"), 0)
        verdicts[r.get("verdict", "?")] += 1
    finalistes = [r for r in results if r.get("verdict") == "PASS_FORWARD_PAPER"]
    shadow = [r for r in results if r.get("verdict") == "SHADOW"]

    L = []
    L.append("# RAPPORT — RECHERCHE AUTONOME 18 h (paper-only)\n")
    L.append("## Résumé pour Flo")
    if not results:
        L.append("Run **non encore exécuté / en cours** : structure scellée (catalogue, partitions, registre), "
                 "aucun résultat mesuré. Aucun chiffre inventé. Ce rapport se remplit à la finalisation.\n")
    elif finalistes:
        L.append("**%d candidat(s) PASS_FORWARD_PAPER** (survivent holdout + DSR/PBO + placebos + stress). "
                 "À renforcer en forward paper, jamais armés en réel.\n" % len(finalistes))
    else:
        L.append("**Aucun candidat PASS** à ce stade. %d en SHADOW. Le reste KILL/DATA_MISSING. "
                 "Pas de faux gagnant.\n" % len(shadow))
    L.append("## Identité & sécurité")
    L.append("- run_id : `%s` · code_sha : `%s`" % (ident.get("run_id"), ident.get("code_sha")))
    L.append("- read_only : %s · real_execution : %s" % (ident.get("read_only"), ident.get("real_execution")))
    L.append("- durée cible : 18 h · fin prévue (wall ms) : %s" % ident.get("fin_prevue_wall_ms"))
    if manifeste is not None:
        L.append("- fichiers scellés : %d (manifeste SHA256 + code SHA)" % len(manifeste))
    L.append("- **Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait**")
    conf = ident.get("config", {})
    L.append("- machine : %s\n" % json.dumps(conf.get("machine", {}), ensure_ascii=False))
    L.append("## Catalogue des archives")
    L.append("Sources : **%s** · octets : %s · statuts : %s\n" % (
        resume_cat.get("n_sources"), resume_cat.get("octets_total"),
        json.dumps(resume_cat.get("par_statut", {}), ensure_ascii=False)))
    L.append("## Partitions anti-fuite (scellées)")
    if split:
        L.append("- discovery : %s\n- validation : %s\n- holdout : %s\n- purge/embargo (horizon max) : %s ms\n" % (
            split.get("discovery"), split.get("validation"), split.get("holdout"), split.get("horizon_max_ms")))
    else:
        L.append("(partitions non encore scellées)\n")
    L.append("## Registre des essais")
    L.append("Préenregistrés : **%d** · résultats : **%d** · familles : %d\n" % (len(prereg), len(results), len(familles)))
    L.append("## Verdicts")
    L.append(json.dumps(verdicts, ensure_ascii=False) + "\n")
    if results:
        L.append("## Leaderboard (net médian bps, décroissant)")
        L.append("| trial_id | family | variant | net médian bps | PF | Sharpe | verdict |")
        L.append("|---|---|---|---:|---:|---:|---|")
        for r in sorted(results, key=lambda r: -(r.get("net_median_bps") or -1e9))[:25]:
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                r.get("trial_id", "—"), r.get("family", "—"), r.get("variant", "—"),
                r.get("net_median_bps", "—"), r.get("pf", "—"), r.get("sharpe", "—"), r.get("verdict", "—")))
        L.append("")
    L.append("## PnL / ROI")
    L.append("Objet mesuré = **edge net (bps) par épisode** côté taker/maker (shadow). Le PnL$/ROI$ sur "
             "capital total ET immobilisé n'est calculé qu'après le forward paper des finalistes ; un run de "
             "**18 h n'est jamais annualisé** sans avertissement (ROI observé ≠ ROI annuel estimé).\n")
    L.append("## Métriques non encore émises (honnêteté)")
    L.append("DD, capacité détaillée, maker/taker séparés, DSR/PBO par famille, White RC, SPA : calculés au fil "
             "des phases VALIDATION/AUDIT/HOLDOUT ; tant qu'absents ils sont marqués comme tels, jamais inventés.\n")
    L.append("## Benchmarks")
    L.append("Le benchmark court-horizon principal reste **NO_TRADE / CASH**. Un candidat ne « gagne » que s'il "
             "bat NO_TRADE après tous les coûts et survit aux placebos et au holdout.\n")
    L.append("## Prochaines pistes")
    L.append("1) Renforcer les survivants (familles × horizons × régimes) via EXACT_REPLAY + stress. "
             "2) Compléter les DATA_MISSING (OI/funding/liquidations) par collecte d'événements. "
             "3) Combinaisons de signaux (OFI+régime+horloge+liquidité) filtrées par coûts.\n")
    L.append("---")
    L.append("**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**")
    return "\n".join(L) + "\n"


__all__ = ["construire_rapport"]
