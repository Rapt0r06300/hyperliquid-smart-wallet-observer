"""JOBS RÉELLEMENT EXÉCUTÉS 24 H/24 (Flo 26/07, AF-P4). Les 7 files ne sont plus « dépilées pour compter » :
chaque tâche est un JOB persistant avec un cycle de vie (QUEUED → RUNNING → DONE/FAILED/RETRYABLE/BLOCKED_DATA),
un job_id, un type, une priorité, une progression/total, une vitesse, un ETA, une raison, un résultat, un
heartbeat et un worker_id. Un moteur EXÉCUTE réellement le job via un handler. Quand aucune nouvelle donnée
n'arrive, `travail_de_fond` génère et EXÉCUTE automatiquement du travail utile (réglages voisins, stress frais,
stress latence, placebos, walk-forward, leave-one-coin-out, leave-one-regime-out, analyse des rejets,
revalidation des pépites). Aucun idle, aucun busy-loop. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
import uuid
from pathlib import Path

ETATS = ("QUEUED", "RUNNING", "DONE", "FAILED", "RETRYABLE", "BLOCKED_DATA")
TERMINAUX = ("DONE", "FAILED", "BLOCKED_DATA")
#: types déterministes (mêmes données -> même résultat) : dédupliqués par signature. La revalidation et
#: l'analyse des rejets ne sont JAMAIS dédupliquées (elles doivent re-tourner sur données fraîches -> pas d'idle).
DEDUP_TYPES = {"stress_frais", "stress_latence", "placebo", "walk_forward",
               "leave_one_coin_out", "leave_one_regime_out", "voisin_parametre"}
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


def signature_job(type_: str, payload: dict | None) -> str:
    """Empreinte déterministe d'un job (type + params du candidat). Deux jobs de même signature = même travail :
    on ne le refait pas (dédup + « les jobs terminés ne sont pas recréés » après crash, FX-4)."""
    p = payload or {}
    cle = (type_, p.get("family", p.get("famille", "GENERIC")), p.get("direction"), p.get("horizon_ms"),
           p.get("seuil"), round(float(p.get("extra_bps", 0) or 0), 3), round(float(p.get("latence_bps", 0) or 0), 3))
    return hashlib.sha256(repr(cle).encode()).hexdigest()[:16]


def nouveau_job(type_: str, *, priorite: int = 5, total: int = 1, payload: dict | None = None) -> dict:
    return {"job_id": uuid.uuid4().hex[:12], "type": type_, "file": TYPE_FILE.get(type_, "exploration_familles"),
            "signature": signature_job(type_, payload), "priorite": int(priorite), "status": "QUEUED",
            "progression": 0, "total": int(total), "vitesse": None, "eta_s": None, "raison": None,
            "resultat": None, "worker_id": None, "heartbeat_ms": int(time.time() * 1000),
            "cree_ms": int(time.time() * 1000), "payload": payload or {}}


# ─────────── handlers RÉELS (chacun fait un vrai calcul, pas un compteur) ───────────
def _nets(ctx, corpus, sens, horizon):
    return ctx["evaluer_promo"](corpus, sens, horizon)


def _famille(ctx, corpus, cand):
    """Rejoue la MÊME famille + MÊME prédicat + MÊMES params du candidat sur `corpus` (FX-4). Si un évaluateur de
    famille est fourni (applique prédicat + seuil), on l'utilise ; sinon repli honnête sur direction+horizon."""
    evf = ctx.get("evaluer_famille")
    if evf is not None:
        return evf(corpus, cand)
    return ctx["evaluer_promo"](corpus, cand["direction"], cand["horizon_ms"])


def _signature_cand(cand: dict) -> dict:
    """Empreinte du candidat rejoué — PROUVE que stress/placebo/LOCO/LORO ont utilisé la même famille/params."""
    return {"rejoue_famille": cand.get("family", cand.get("famille", "GENERIC")), "rejoue_seuil": cand.get("seuil"),
            "rejoue_direction": cand.get("direction"), "rejoue_horizon_ms": cand.get("horizon_ms")}


def _h_stress_frais(ctx, job):
    cand = job["payload"]; nets = _famille(ctx, ctx["corpus"], cand)
    if not nets:
        return "BLOCKED_DATA", {"raison": "AUCUN_NET_PROMOUVABLE", **_signature_cand(cand)}
    extra = float(job["payload"].get("extra_bps", 3.0))
    med = statistics.median([x - extra for x in nets])
    return "DONE", {"survit_stress_frais": med > 0, "net_median_stresse_bps": round(med, 3), "n": len(nets), **_signature_cand(cand)}


def _h_stress_latence(ctx, job):
    cand = job["payload"]; nets = _famille(ctx, ctx["corpus"], cand)
    if not nets:
        return "BLOCKED_DATA", {"raison": "AUCUN_NET_PROMOUVABLE", **_signature_cand(cand)}
    penal = float(job["payload"].get("latence_bps", 2.0))
    med = statistics.median([x - penal for x in nets])
    return "DONE", {"survit_stress_latence": med > 0, "net_median_bps": round(med, 3), **_signature_cand(cand)}


def _h_placebo(ctx, job):
    cand = job["payload"]
    reel = _famille(ctx, ctx["corpus"], cand)
    opp = _famille(ctx, ctx["corpus"], {**cand, "direction": -cand["direction"]})   # MÊME famille/params, direction opposée
    if not reel or not opp:
        return "BLOCKED_DATA", {"raison": "PLACEBO_SANS_DONNEE", **_signature_cand(cand)}
    return "DONE", {"reel_median_bps": round(statistics.median(reel), 3),
                    "placebo_median_bps": round(statistics.median(opp), 3),
                    "placebo_distinct": abs(statistics.median(opp) + statistics.median(reel)) > 1e-6,
                    **_signature_cand(cand)}


def _h_walk_forward(ctx, job):
    """Walk-forward SANS zip(corpus, nets filtrés) : on évalue PAR ÉPISODE (chaque objet garde SON ts et son
    net), on ne réassocie jamais deux listes de longueurs potentiellement différentes. Embargo RÉEL (FX-4/FX-9)."""
    import validation_18h as V18
    import pipeline_18h as PL
    cand = job["payload"]
    ev = ctx.get("evaluer_objets")
    if ev is None:
        return "BLOCKED_DATA", {"raison": "PAS_D_EVALUATEUR_OBJETS"}
    objs = ev(ctx["corpus"], cand["direction"], cand["horizon_ms"])   # objets par épisode (ts+net LIÉS, jamais zip)
    eps = [{"ts_ms": o.get("entry_ts", o.get("ts_ms")), "net_bps": o.get("net_bps")}
           for o in objs if o.get("status") == "OK" and o.get("promotable")
           and o.get("exit_source") == "FWD_BOOK" and o.get("entry_ts") is not None]
    if len(eps) < 8:
        return "BLOCKED_DATA", {"raison": "TROP_PEU_POUR_WF", "n_promouvables": len(eps)}
    emb = PL.embargo_reel([cand["horizon_ms"]])               # FX-9 : embargo RÉEL, jamais 1 ms
    wf = V18.walk_forward(eps, k=3, embargo_ms=emb)
    return "DONE", {"wf_oos_net_median_bps": wf.get("oos_net_median_bps"), "embargo_ms": emb, "n_oos": wf.get("n")}


def _h_loco(ctx, job):
    cand = job["payload"]; coins = sorted({e.get("coin") for e in ctx["corpus"]})
    if len(coins) < 2:
        return "BLOCKED_DATA", {"raison": "UN_SEUL_COIN"}
    res = {}
    for c in coins:
        sub = [e for e in ctx["corpus"] if e.get("coin") != c]
        nets = _famille(ctx, sub, cand)                       # MÊME famille/prédicat/params, un coin retiré
        res[c] = round(statistics.median(nets), 3) if nets else None
    return "DONE", {"leave_one_coin_out": res, "robuste": all((v or -1) > 0 for v in res.values()), **_signature_cand(cand)}


def _h_loro(ctx, job):
    cand = job["payload"]; regs = sorted({e.get("regime") for e in ctx["corpus"] if e.get("regime")})
    if len(regs) < 2:
        return "BLOCKED_DATA", {"raison": "UN_SEUL_REGIME"}
    res = {}
    for r in regs:
        sub = [e for e in ctx["corpus"] if e.get("regime") != r]
        nets = _famille(ctx, sub, cand)                       # MÊME famille/prédicat/params, un régime retiré
        res[r] = round(statistics.median(nets), 3) if nets else None
    return "DONE", {"leave_one_regime_out": res, **_signature_cand(cand)}


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
    cand = job["payload"]; nets = _famille(ctx, ctx["corpus"], cand)
    if not nets:
        return "BLOCKED_DATA", {"raison": "PEPITE_SANS_DONNEE_FRAICHE", **_signature_cand(cand)}
    return "DONE", {"net_median_frais_bps": round(statistics.median(nets), 3), "n": len(nets),
                    "tient_encore": statistics.median(nets) > 0, **_signature_cand(cand)}


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
    """Persistance append-only des jobs (jobs.jsonl) : cycle de vie complet PERSISTÉ (QUEUED avant exécution,
    RUNNING pendant, puis terminal). Reprenable : l'état courant d'un job = son DERNIER enregistrement. Après
    crash, les RUNNING orphelins deviennent RETRYABLE ; les signatures évitent de refaire un travail terminé."""

    def __init__(self, rundir: Path):
        self.dir = Path(rundir) / "jobs"; self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "jobs.jsonl"

    def enregistrer(self, job: dict):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")

    def enfiler(self, job: dict) -> dict:
        """Écrit le job en QUEUED AVANT toute exécution (le worker le prendra ensuite)."""
        job["status"] = "QUEUED"; job["heartbeat_ms"] = int(time.time() * 1000)
        self.enregistrer(job)
        return job

    def _stream(self):
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", errors="ignore") as f:   # STREAMING, pas splitlines()
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    yield json.loads(l)
                except ValueError:
                    continue

    def dernier_par_id(self) -> dict:
        """État COURANT de chaque job = son dernier enregistrement (le fichier est append-only)."""
        etats = {}
        for e in self._stream():
            jid = e.get("job_id")
            if jid is not None:
                etats[jid] = e
        return etats

    def signatures_terminales(self) -> set:
        return {e.get("signature") for e in self.dernier_par_id().values() if e.get("status") in TERMINAUX}

    def reprise_apres_crash(self) -> dict:
        """Tout job dont le DERNIER état est RUNNING = interrompu par un crash -> réenregistré RETRYABLE
        (jamais perdu, jamais dupliqué). Les jobs déjà terminaux ne sont pas recréés."""
        n = 0
        for e in self.dernier_par_id().values():
            if e.get("status") == "RUNNING":
                self.enregistrer({**e, "status": "RETRYABLE", "raison": "REPRISE_APRES_CRASH",
                                  "heartbeat_ms": int(time.time() * 1000)})
                n += 1
        return {"n_running_orphelins_retryable": n}

    def compte(self) -> dict:
        """Compte par état COURANT (dernier enregistrement par job), pas par nombre de lignes."""
        c = {e: 0 for e in ETATS}
        for e in self.dernier_par_id().values():
            st = e.get("status", "QUEUED")
            c[st] = c.get(st, 0) + 1
        return c


def _executer_cycle_de_vie(store: JobStore, j: dict, ctx: dict) -> dict:
    """Cycle de vie PERSISTÉ d'un job : QUEUED (avant exécution) -> RUNNING (publié, heartbeat) -> terminal.
    Chaque transition est append-only, donc reprenable après crash."""
    store.enfiler(j)                                         # 1) QUEUED persisté AVANT toute exécution
    j["status"] = "RUNNING"; j["worker_id"] = "w0"; j["heartbeat_ms"] = int(time.time() * 1000)
    store.enregistrer(dict(j))                               # 2) RUNNING publié (un worker l'a pris)
    executer_job(j, contexte=ctx)                            # 3) exécution réelle -> DONE/FAILED/RETRYABLE/BLOCKED_DATA
    store.enregistrer(j)                                     # 4) terminal persisté
    return j


def travail_de_fond(rundir: Path, contexte: dict, *, candidats: list, rejets: list | None = None,
                    dedupe: bool = True) -> dict:
    """AUCUN IDLE : génère et EXÉCUTE du travail utile pour chaque candidat (stress frais/latence, placebo, WF,
    LOCO, LORO, voisins, revalidation) + une analyse des rejets. Cycle de vie PERSISTÉ (QUEUED→RUNNING→terminal).
    REPRISE après crash (RUNNING orphelins -> RETRYABLE). Les jobs déterministes déjà terminés (même signature)
    ne sont PAS recréés ; la revalidation et l'analyse des rejets tournent toujours (données fraîches)."""
    store = JobStore(rundir)
    reprise = store.reprise_apres_crash()                    # FX-4 : RUNNING orphelins -> RETRYABLE
    sigs_done = store.signatures_terminales() if dedupe else set()
    ctx = {**contexte, "rejets": rejets or []}
    types = ["stress_frais", "stress_latence", "placebo", "walk_forward", "leave_one_coin_out",
             "leave_one_regime_out", "voisin_parametre", "revalidation_pepite"]
    executes, ignores = [], []
    for cand in (candidats or [{"direction": 1, "horizon_ms": 1000, "seuil": 8}]):
        for t in types:
            j = nouveau_job(t, priorite=(3 if t.startswith("stress") else 5), payload=dict(cand))
            if dedupe and t in DEDUP_TYPES and j["signature"] in sigs_done:
                ignores.append(j["signature"]); continue     # déjà fait sur ces données -> pas recréé (anti-répétition)
            _executer_cycle_de_vie(store, j, ctx)
            executes.append(j); sigs_done.add(j["signature"])
    ja = nouveau_job("analyse_rejets", priorite=6, payload={})
    _executer_cycle_de_vie(store, ja, ctx); executes.append(ja)   # jamais dédupliqué -> aucun idle
    par_type = {}
    for j in executes:
        par_type.setdefault(j["type"], {"DONE": 0, "BLOCKED_DATA": 0, "AUTRE": 0})
        k = j["status"] if j["status"] in ("DONE", "BLOCKED_DATA") else "AUTRE"
        par_type[j["type"]][k] += 1
    resume = {"n_jobs_executes": len(executes),
              "n_done": sum(1 for j in executes if j["status"] == "DONE"),
              "n_bloques_data": sum(1 for j in executes if j["status"] == "BLOCKED_DATA"),
              "n_ignores_dedupe": len(ignores), "reprise_apres_crash": reprise,
              "par_type": par_type, "aucun_idle": len(executes) > 0, "compte_store": store.compte()}
    _ecrire(rundir / "jobs" / "travail_de_fond.json", resume)
    return resume


def _ecrire(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


__all__ = ["ETATS", "TERMINAUX", "DEDUP_TYPES", "FILES", "TYPE_FILE", "nouveau_job", "signature_job",
           "executer_job", "JobStore", "travail_de_fond", "HANDLERS"]
