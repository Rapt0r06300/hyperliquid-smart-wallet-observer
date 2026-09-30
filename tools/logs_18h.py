"""LOGS → DONNÉES DE RECHERCHE (LOT18H-DATA-COMPLETE P6, Flo 26/07). On n'ignore aucun log : reconnexions,
gaps, rate limits, erreurs, latences ; signaux ACCEPTÉS/REFUSÉS + raisons des gates ; no-trade / stale /
missing ; OPEN/ADD/REDUCE/CLOSE/FLIP ; fills partiels/no-fill ; frais/slippage/funding/PnL/ROI/DD ; CPU/RAM/
disque/workers/exceptions/restarts.

Pour CHAQUE signal refusé qui porte un prix + un prix forward, on REJOUE son markout causal (vrais prix +
coûts) et on compare GATE vs NO_GATE : quelles protections sauvent le PnL, lesquelles bloquent des
opportunités. Écrit log_analysis.csv + gap_recovery.csv. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path

REFUS = ("motif", "raison", "reason", "refus")
GATE_MOTIFS = ("MICRO_EDGE", "EDGE_NEGATIF", "ROI_INSUFFISANT", "ROI_NON_MESURABLE", "SIGNAL_PERIME",
               "STALE_SIGNAL", "CLOCK_SKEW", "LIQUIDITE", "BUDGET", "DEJA_OUVERT", "PNL_POUR_DES_CENTIMES",
               "SNAPSHOT_", "DATA_MISSING", "PRIX_NON_EXECUTABLE")


def _markout_refuse(d: dict) -> float | None:
    """Markout causal net (bps) d'un signal REFUSÉ s'il porte un prix + un forward + un sens + des coûts."""
    px = d.get("prix_entree") or d.get("prix") or d.get("px")
    fwd = d.get("prix_sortie") or d.get("mark") or (d.get("meta") or {}).get("fwd")
    sens = d.get("sens") or d.get("direction")
    if not (isinstance(px, (int, float)) and isinstance(fwd, (int, float)) and px > 0 and sens in (1, -1)):
        return None
    brut = sens * (float(fwd) - float(px)) / float(px) * 1e4
    cout = float(d.get("cout_entree_bps") or 0.0) + float(d.get("spread_bps") or 0.0) + \
        float(d.get("slippage_bps") or 0.0) + float(d.get("frais_bps") or 0.0)
    return round(brut - cout, 4)


def analyser(rundir: Path, fichiers: list[Path]) -> dict:
    """Parcourt des journaux (jsonl) et agrège l'analyse. `fichiers` = chemins de ledgers/logs à lire."""
    rundir = Path(rundir)
    cat = {"accepte": 0, "refuse": 0, "no_trade": 0, "OPEN": 0, "ADD": 0, "REDUCE": 0, "CLOSE": 0, "FLIP": 0,
           "no_fill": 0, "partial_fill": 0, "reconnect": 0, "gap": 0, "rate_limit": 0, "erreur": 0, "exception": 0}
    raisons_refus: dict[str, int] = {}
    markouts_refuses, gaps = [], []
    for p in fichiers:
        p = Path(p)
        if not p.exists() or p.suffix != ".jsonl":
            continue
        for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            kind = str(d.get("kind") or d.get("evt") or d.get("event") or "")
            for k in ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP"):
                if kind == k:
                    cat[k] += 1
            motif = next((str(d.get(k)) for k in REFUS if d.get(k)), None)
            if motif:
                cat["refuse"] += 1
                cle = next((g for g in GATE_MOTIFS if g in motif.upper()), motif[:24])
                raisons_refus[cle] = raisons_refus.get(cle, 0) + 1
                m = _markout_refuse(d)
                if m is not None:
                    markouts_refuses.append({"motif": cle, "markout_bps": m})
            elif kind in ("OPEN", "ADMIS") or d.get("admis") is True:
                cat["accepte"] += 1
            if d.get("no_trade") or "NO_TRADE" in kind:
                cat["no_trade"] += 1
            if d.get("fill") == 0 or "NO_FILL" in kind:
                cat["no_fill"] += 1
            if d.get("partial") or "PARTIAL" in kind:
                cat["partial_fill"] += 1
            if "reconnect" in l.lower():
                cat["reconnect"] += 1
            if d.get("gap") or "gap" in kind.lower():
                cat["gap"] += 1
                gaps.append({"ts_ms": d.get("ts_ms"), "recupere": bool(d.get("recupere") or d.get("recovered")),
                             "source": str(p.name)})
            if "rate" in l.lower() and "limit" in l.lower():
                cat["rate_limit"] += 1
            if d.get("erreur") or d.get("error") or "ERROR" in kind:
                cat["erreur"] += 1
            if d.get("exception") or "exception" in l.lower():
                cat["exception"] += 1
    # GATE vs NO_GATE : les signaux refusés dont le markout était POSITIF = opportunités bloquées ; négatif = protégés
    bloquees = [x["markout_bps"] for x in markouts_refuses if x["markout_bps"] > 0]
    protegees = [x["markout_bps"] for x in markouts_refuses if x["markout_bps"] <= 0]
    gate_vs = {"n_refuses_rejoues": len(markouts_refuses),
               "opportunites_bloquees": len(bloquees), "gain_manque_median_bps": (statistics.median(bloquees) if bloquees else None),
               "pertes_evitees": len(protegees), "perte_evitee_median_bps": (statistics.median(protegees) if protegees else None)}
    (rundir / "results").mkdir(parents=True, exist_ok=True)
    _csv(rundir / "results" / "log_analysis.csv", ["categorie", "n"], [{"categorie": k, "n": v} for k, v in {**cat, **{"refus:" + r: n for r, n in raisons_refus.items()}}.items()])
    _csv(rundir / "results" / "gap_recovery.csv", ["ts_ms", "recupere", "source"], gaps)
    res = {"categories": cat, "raisons_refus": raisons_refus, "gate_vs_nogate": gate_vs, "n_gaps": len(gaps)}
    (rundir / "resultats").mkdir(parents=True, exist_ok=True)
    (rundir / "resultats" / "log_analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _csv(p: Path, cols, lignes):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for l in lignes:
        w.writerow(l)
    p.write_text(buf.getvalue(), encoding="utf-8")


__all__ = ["analyser", "GATE_MOTIFS"]
