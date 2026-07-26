"""JOBS RÉELLEMENT EXÉCUTÉS 24 H/24 (Flo 26/07, AF-P4). Les 7 files ne sont plus « dépilées pour compter » :
chaque tâche est un JOB persistant avec un cycle de vie (QUEUED → RUNNING → DONE/FAILED/RETRYABLE/BLOCKED_DATA),
un job_id, un type, une priorité, une progression/total, une vitesse, un ETA, une raison, un résultat, un
heartbeat et un worker_id. Un moteur EXÉCUTE réellement le job via un handler. Quand aucune nouvelle donnée
n'arrive, `travail_de_fond` génère et EXÉCUTE automatiquement du travail utile (réglages voisins, stress frais,
stress latence, placebos, walk-forward, leave-one-coin-out, leave-one-regime-out, analyse des rejets,
revalidation des pépites). Aucun idle, aucun busy-loop. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import uuid
from pathlib import Path

ETATS = ("QUEUED", "RUNNING", "DONE", "FAILED", "RETRYABLE", "BLOCKED_DATA")
FILES = ("ingestion_sante", "forward_figes", "exact_survivants", "validation_stress",
         "exploration_familles", "amelioration_locale", "analyse_rejets")
#: type de job -> file prioritaire de rattachement.
TYPE_FILE = {
    "ingestion_sante": "ingestion_sante", "forward_fige": "forward_figes", "exact_survivant": "exact_survivants",
    "stress_frais": "validation_stress", "stress_latence": "validation_stress", "placebo": "validation_stress",
    "walk_forward": "validation_stress", "leave_one_coin_out": "validation_stress",
    "leave_one_regime_out": "validation_stress", "exploration": "exploration_familles",
    "voisin_parametre": "amelioration_locale", "revalidation_pepite": "amelioration_locale",
    "analyse_rejets": "analyse_rejets",
}


def nouveau_job(type_: str, *, priorite: int = 5, total: int = 1, payload: dict | None = None) -> dict:
    return {"job_id": uuid.uuid4().hex[:12], "type": type_, "file": TYPE_FILE.get(type_, "exploration_familles"),
            "priorite": int(priorite), "status": "QUEUED", "progression": 0, "total": int(total),
            "vitesse": None, "eta_s": None, "raison": None, "resultat": None, "worker_id": None,
            "heartbeat_ms": int(time.time() * 1000), "cree_ms": int(time.time() * 1000), "payload": payload or {}}


# ─────────── handlers RÉELS (chacun fait un vrai calcul, pas un compteur) ───────────
def _nets(ctx, corpus, sens, horizon):
    return ctx["evaluer_promo"](corpus, sens, horizon)


def _h_stress_frais(ctx, job):
    cand = job["payload"]; nets = _nets(ctx, ctx["corpus"], cand["direction"], cand["horizon_ms"])
    if not nets:
        return "BLOCKED_DATA", {"raison": "AUCUN_NET_PROMOUVABLE"}
    extra = float(job["payload"].get("extra_bps", 3.0))
    med = statistics.median([x - extra for x in nets])
    return "DONE", {"survit_stress_frais": med > 0, "net_median_stresse_bps": round(med, 3), "n": len(nets)}


def _h_stress_latence(ctx, job):
    cand = job["payload"]; nets = _nets(ctx, ctx["corpus"], cand["direction"], cand["horizon_ms"])
    if not nets:
        return "BLOCKED_DATA", {"raison": "AUCUN_NET_PROMOUVABLE"}
    penal = float(job["payload"].get("latence_bps", 2.0))
    med = statistics.median([x - penal for x in nets])
    return "DONE", {"survit_stress_latence": med > 0, "net_median_bps": round(med, 3)}


def _h_placebo(ctx, job):
    cand = job["payload"]
    reel = _nets(ctx, ctx["corpus"], cand["direction"], cand["horizon_ms"])
    opp = _nets(ctx, ctx["corpus"], -cand["direction"], cand["horizon_ms"])
    if not reel or not opp:
        return "BLOCKED_DATA", {"raison": "PLACEBO_SANS_DONNEE"}
    return "DONE", {"reel_median_bps": round(statistics.median(reel), 3),
                    "placebo_median_bps": round(statistics.median(opp), 3),
                    "placebo_distinct": abs(statistics.median(opp) + statistics.median(reel)) > 1e-6}


def _h_walk_forward(ctx, job):
    import validation_18h as V18
    cand = job["payload"]
    eps = [{"ts_ms": e.get("ts_ms", i), "net_bps": n}
           for i, (e, n) in enumerate(zip(ctx["corpus"], _nets(ctx, ctx["corpus"], cand["direction"], cand["horizon_ms"])))]
    if len(eps) < 8:
        return "BLOCKED_DATA", {"raison": "TROP_PEU_POUR_WF"}
    wf = V18.walk_forward(eps, k=3, embargo_ms=1.0)
    return "DONE", {"wf_oos_net_median_bps": wf.get("oos_net_median_bps")}


def _h_loco(ctx, job):
    cand = job["payload"]; coins = sorted({e.get("coin") for e in ctx["corpus"]})
    if len(coins) < 2:
        return "BLOCKED_DATA", {"raison": "UN_SEUL_COIN"}
    res = {}
    for c in coins:
        sub = [e for e in ctx["corpus"] if e.get("coin") != c]
        nets = _nets(ctx, sub, cand["direction"], cand["horizon_ms"])
        res[c] = round(statistics.median(nets), 3) if nets else None
    return "DONE", {"leave_one_coin_out": res, "robuste": all((v or -1) > 0 for v in res.values())}


def _h_loro(ctx, job):
    cand = job["payload"]; regs = sorted({e.get("regime") for e in ctx["corpus"] if e.get("regime")})
    if len(regs) < 2:
        return "BLOCKED_DATA", {"raison": "UN_SEUL_REGIME"}
    res = {}
    for r in regs:
        sub = [e for e in ctx["corpus"] if e.get("regime") != r]
        nets = _nets(ctx, sub, cand["direction"], cand["horizon_ms"])
        res[r] = round(statistics.median(nets), 3) if nets else None
    return "DONE", {"leave_one_regime_out": res}


def _h_voisin(ctx, job):
    """Réglage voisin : réévalue le candidat à seuil±1 via le prédicat de sa famille (amélioration locale)."""
    cand = job["payload"]
    ev = ctx.get("evaluer_seuil")
    if ev is None:
        return "BLOCKED_DATA", {"raison": "PAS_D_EVALUATEUR_SEUIL"}
    base = int(cand.get("seuil", 8)); courbe = {}
    for s in (base - 1, base, base + 1):
        nets = ev(cand, s)
        courbe[s] = round(statistics.median(nets), 3) if nets else None
    return "DONE", {"voisins": courbe}


def _h_revalidation(ctx, job):
    cand = job["payload"]; nets = _nets(ctx, ctx["corpus"], cand["direction"], cand["horizon_ms"])
    if not nets:
        return "BLOCKED_DATA", {"raison": "PEPITE_SANS_DONNEE_FRAICHE"}
    return "DONE", {"net_median_frais_bps": round(statistics.median(nets), 3), "n": len(nets),
                    "tient_encore": statistics.median(nets) > 0}


def _h_analyse_rejets(ctx, job):
    rejets = ctx.get("rejets") or []
    par_raison = {}
    for r in rejets:
        for m in (r.get("raisons") or ["INCONNU"]):
            par_raison[m] = par_raison.get(m, 0) + 1
    return "DONE", {"n_rejets": len(rejets), "par_raison": par_raison}


def _h_sante(ctx, job):
    return "DONE", {"corpus_n": len(ctx.get("corpus") or []), "ok": bool(ctx.get("corpus"))}


HANDLERS = {"stress_frais": _h_stress_frais, "stress_latence": _h_stress_latence, "placebo": _h_placebo,
            "walk_forward": _h_walk_forward, "leave_one_coin_out": _h_loco, "leave_one_regime_out": _h_loro,
            "voisin_parametre": _h_voisin, "revalidation_pepite": _h_revalidation,
            "analyse_rejets": _h_analyse_rejets, "ingestion_sante": _h_sante, "forward_fige": _h_revalidation,
            "exact_survivant": _h_revalidation, "exploration": _h_voisin}


def executer_job(job: dict, *, contexte: dict, worker_id: str = "w0") -> dict:
    """Exécute RÉELLEMENT le job via son handler ; met à jour status/progression/vitesse/ETA/résultat/heartbeat."""
    t0 = time.time()
    job["status"] = "RUNNING"; job["worker_id"] = worker_id; job["heartbeat_ms"] = int(t0 * 1000)
    h = HANDLERS.get(job["type"])
    try:
        if h is None:
            job["status"], job["resultat"] = "FAILED", {"raison": "TYPE_INCONNU:%s" % job["type"]}
        else:
            st, res = h(contexte, job)
            job["status"], job["resultat"] = st, res
            if st == "BLOCKED_DATA":
                job["raison"] = (res or {}).get("raison")
    except Exception as e:  # noqa: BLE001 — un job qui échoue est RETRYABLE, jamais silencieux
        job["status"], job["resultat"], job["raison"] = "RETRYABLE", {"exception": str(e)[:160]}, "EXCEPTION"
    dt = max(1e-6, time.time() - t0)
    job["progression"] = job["total"]; job["vitesse"] = round(job["total"] / dt, 3)
    job["eta_s"] = 0.0; job["heartbeat_ms"] = int(time.time() * 1000); job["duree_s"] = round(dt, 4)
    return job


class JobStore:
    """Persistance append-only des jobs (jobs.jsonl) + index d'état — reprenable."""

    def __init__(self, rundir: Path):
        self.dir = Path(rundir) / "jobs"; self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "jobs.jsonl"

    def enregistrer(self, job: dict):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")

    def compte(self) -> dict:
        c = {e: 0 for e in ETATS}
        if self.path.exists():
            for l in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    c[json.loads(l).get("status", "QUEUED")] = c.get(json.loads(l).get("status", "QUEUED"), 0) + 1
                except ValueError:
                    continue
        return c


def travail_de_fond(rundir: Path, contexte: dict, *, candidats: list, rejets: list | None = None) -> dict:
    """AUCUN IDLE : quand il n'y a pas de nouvelle donnée, génère et EXÉCUTE du travail utile pour chaque
    candidat (stress frais/latence, placebo, WF, LOCO, LORO, voisins, revalidation) + une analyse des rejets.
    Rend un résumé prouvant que des jobs ont été RÉELLEMENT exécutés (status DONE/BLOCKED_DATA, pas comptés)."""
    store = JobStore(rundir)
    ctx = {**contexte, "rejets": rejets or []}
    types = ["stress_frais", "stress_latence", "placebo", "walk_forward", "leave_one_coin_out",
             "leave_one_regime_out", "voisin_parametre", "revalidation_pepite"]
    executes = []
    for cand in (candidats or [{"direction": 1, "horizon_ms": 1000, "seuil": 8}]):
        for t in types:
            j = nouveau_job(t, priorite=(3 if t.startswith("stress") else 5), payload=dict(cand))
            executer_job(j, contexte=ctx)
            store.enregistrer(j); executes.append(j)
    ja = nouveau_job("analyse_rejets", priorite=6, payload={}); executer_job(ja, contexte=ctx)
    store.enregistrer(ja); executes.append(ja)
    par_type = {}
    for j in executes:
        par_type.setdefault(j["type"], {"DONE": 0, "BLOCKED_DATA": 0, "AUTRE": 0})
        k = j["status"] if j["status"] in ("DONE", "BLOCKED_DATA") else "AUTRE"
        par_type[j["type"]][k] += 1
    resume = {"n_jobs_executes": len(executes),
              "n_done": sum(1 for j in executes if j["status"] == "DONE"),
              "n_bloques_data": sum(1 for j in executes if j["status"] == "BLOCKED_DATA"),
              "par_type": par_type, "aucun_idle": len(executes) > 0, "compte_store": store.compte()}
    _ecrire(rundir / "jobs" / "travail_de_fond.json", resume)
    return resume


def _ecrire(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


__all__ = ["ETATS", "FILES", "TYPE_FILE", "nouveau_job", "executer_job", "JobStore", "travail_de_fond", "HANDLERS"]
