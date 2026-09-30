"""PROGRESSION LIVE PARTAGÉE (Flo 26/07, FX-2). Petit état thread-safe que le moteur met à jour PENDANT les
calculs (pas seulement en fin de cycle) et que le thread du dashboard lit en direct (même process). Sert à
remplir fait/total/pourcentage/vitesse/ETA/job/prochaine — plus JAMAIS des None décoratifs. 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections import deque
import statistics
import threading
import time

_LOCK = threading.Lock()
_JOURNAL_MAX = 16
_JOURNAL: list[dict] = []
_SEQUENCE = 0
_DERNIER_JOURNAL_TS = 0.0
_ECHANTILLONS: deque[dict] = deque(maxlen=240)
_DEBITS_HISTORIQUES: dict[tuple[str, str], deque[float]] = {}
_PHASE_DEBUT: dict[tuple[str, str], tuple[float, float]] = {}
_ETAT = {
    "fait": 0,
    "total": 0,
    "job": None,
    "ensuite": None,
    "detail": None,
    "sous_fait": None,
    "sous_total": None,
    "traite": None,
    "traite_total": None,
    "unite": None,
    "t0": None,
    "maj": None,
    "compteur_maj": None,
    "heartbeat_maj": None,
    "sous_tache_t0": None,
    "heartbeat_sequence": 0,
}


def _scope(etat: dict) -> tuple[str, str]:
    return (str(etat.get("job") or "calcul"), str(etat.get("unite") or "éléments"))


def _compteur(etat: dict) -> tuple[float, float, str]:
    """Choisit le compteur le plus fin réellement mesuré."""
    traite = etat.get("traite")
    traite_total = etat.get("traite_total")
    if traite is not None and traite_total:
        return float(traite), float(traite_total), "interne"
    sous_fait = etat.get("sous_fait")
    sous_total = etat.get("sous_total")
    if sous_fait is not None and sous_total:
        return float(sous_fait), float(sous_total), "sous_phase"
    return float(etat.get("fait") or 0), float(etat.get("total") or 0), "global"


def _debit_initial(unite: str) -> float:
    """Projection de démarrage conservatrice, remplacée dès les premières mesures."""
    u = (unite or "").lower()
    if "octet" in u or "byte" in u:
        return 16.0 * 1024.0 * 1024.0
    if "fichier" in u or "source" in u:
        return 1.0
    if "événement" in u or "event" in u or "ligne" in u:
        return 5_000.0
    if "combinaison" in u or "variante" in u or "trial" in u:
        return 0.02
    return 0.25


def _terminer_phase_locked(scope: tuple[str, str], now: float) -> None:
    debut = _PHASE_DEBUT.pop(scope, None)
    if debut is None:
        return
    started_at, total = debut
    duree = now - started_at
    if duree <= 0 or total <= 0:
        return
    debit = total / duree
    historique = _DEBITS_HISTORIQUES.setdefault(scope, deque(maxlen=12))
    historique.append(debit)


def _enregistrer_echantillon_locked(now: float, *, force: bool = False) -> None:
    done, total, mode = _compteur(_ETAT)
    scope = _scope(_ETAT)
    if not force and _ECHANTILLONS:
        dernier = _ECHANTILLONS[-1]
        if dernier["scope"] == scope and dernier["done"] == done and dernier["total"] == total:
            return
    _ECHANTILLONS.append({
        "ts": now,
        "scope": scope,
        "done": done,
        "total": total,
        "mode": mode,
    })
    _ETAT["compteur_maj"] = now
    if scope not in _PHASE_DEBUT:
        _PHASE_DEBUT[scope] = (now, total)
    if total > 0 and done >= total:
        _terminer_phase_locked(scope, now)


def _ajouter_journal_locked(message: str, *, niveau: str = "INFO", force: bool = False) -> None:
    """Ajoute une activité utile sans transformer chaque compteur en torrent de texte."""
    global _SEQUENCE, _DERNIER_JOURNAL_TS
    message = " ".join(str(message or "").split())
    if not message:
        return
    now = time.time()
    if not force and _JOURNAL:
        if _JOURNAL[-1]["message"] == message:
            return
        if now - _DERNIER_JOURNAL_TS < 0.75:
            return
    _SEQUENCE += 1
    _DERNIER_JOURNAL_TS = now
    _JOURNAL.append({
        "sequence": _SEQUENCE,
        "ts": now,
        "heure": time.strftime("%H:%M:%S", time.localtime(now)),
        "niveau": str(niveau or "INFO").upper(),
        "message": message[:240],
    })
    del _JOURNAL[:-_JOURNAL_MAX]


def journaliser(message: str, *, niveau: str = "INFO") -> None:
    """Publie explicitement une activité importante dans la console de supervision."""
    with _LOCK:
        _ajouter_journal_locked(message, niveau=niveau, force=True)


def reset(total: int = 0, *, job: str | None = None, ensuite: str | None = None):
    with _LOCK:
        now = time.time()
        ancienne_scope = _scope(_ETAT)
        _terminer_phase_locked(ancienne_scope, now)
        _ECHANTILLONS.clear()
        _ETAT.update(
            fait=0,
            total=int(total),
            job=job,
            ensuite=ensuite,
            detail=None,
            sous_fait=None,
            sous_total=None,
            traite=None,
            traite_total=None,
            unite=None,
            t0=now,
            maj=now,
            compteur_maj=now,
            heartbeat_maj=now,
            sous_tache_t0=now,
            heartbeat_sequence=0,
        )
        _enregistrer_echantillon_locked(now, force=True)
        _ajouter_journal_locked(
            "Nouveau cycle : %s%s" % (
                job or "initialisation",
                (" -> ensuite %s" % ensuite) if ensuite else "",
            ),
            niveau="ETAPE",
            force=True,
        )


def publier(
    fait: int,
    total: int | None = None,
    *,
    job: str | None = None,
    ensuite: str | None = None,
    detail: str | None = None,
    sous_fait: int | None = None,
    sous_total: int | None = None,
    traite: int | None = None,
    traite_total: int | None = None,
    unite: str | None = None,
):
    """Publie la progression principale et, si disponible, celle de la boucle interne.

    ``fait/total`` décrit les variantes ou étapes. ``traite/traite_total`` décrit
    les événements parcourus dans la variante courante. Cette seconde granularité
    évite qu'un calcul exact de plusieurs minutes ressemble à un freeze.
    """
    with _LOCK:
        now = time.time()
        if _ETAT["t0"] is None:
            _ETAT["t0"] = now
        ancienne_sous_tache = (_ETAT.get("job"), _ETAT.get("detail"))
        ancienne_scope = _scope(_ETAT)
        ancien_compteur = _compteur(_ETAT)
        ancien_fait = int(_ETAT.get("fait") or 0)
        if int(fait) != ancien_fait:
            if sous_fait is None:
                _ETAT["sous_fait"] = None
                _ETAT["sous_total"] = None
            if traite is None:
                _ETAT["traite"] = None
                _ETAT["traite_total"] = None
        _ETAT["fait"] = int(fait)
        if total is not None:
            _ETAT["total"] = int(total)
        if job is not None:
            _ETAT["job"] = job
        if ensuite is not None:
            _ETAT["ensuite"] = ensuite
        if detail is not None:
            _ETAT["detail"] = detail
        if sous_fait is not None:
            _ETAT["sous_fait"] = max(0, int(sous_fait))
        if sous_total is not None:
            _ETAT["sous_total"] = max(0, int(sous_total))
        if traite is not None:
            _ETAT["traite"] = max(0, int(traite))
        if traite_total is not None:
            _ETAT["traite_total"] = max(0, int(traite_total))
        if unite is not None:
            _ETAT["unite"] = unite
        if ancienne_sous_tache != (_ETAT.get("job"), _ETAT.get("detail")):
            _ETAT["sous_tache_t0"] = now
        _ETAT["maj"] = now
        _ETAT["heartbeat_maj"] = now
        _ETAT["heartbeat_sequence"] = int(_ETAT.get("heartbeat_sequence") or 0) + 1
        nouvelle_scope = _scope(_ETAT)
        nouveau_compteur = _compteur(_ETAT)
        if ancienne_scope != nouvelle_scope:
            _terminer_phase_locked(ancienne_scope, now)
            _PHASE_DEBUT[nouvelle_scope] = (now, nouveau_compteur[1])
            _enregistrer_echantillon_locked(now, force=True)
        elif ancien_compteur != nouveau_compteur:
            _enregistrer_echantillon_locked(now)
        nouveau_job = _ETAT.get("job") or "calcul"
        nouveau_detail = _ETAT.get("detail")
        if ancien_fait != int(fait):
            _ajouter_journal_locked(
                "Etape %d/%d : %s%s" % (
                    int(fait),
                    int(_ETAT.get("total") or 0),
                    nouveau_job,
                    (" - %s" % nouveau_detail) if nouveau_detail else "",
                ),
                niveau="ETAPE",
                force=True,
            )
        elif ancienne_sous_tache != (nouveau_job, nouveau_detail):
            _ajouter_journal_locked(
                "%s%s" % (
                    nouveau_job,
                    (" - %s" % nouveau_detail) if nouveau_detail else "",
                ),
                niveau="ACTIVITE",
            )


def pulse(
    *,
    detail: str,
    traite: int | None = None,
    traite_total: int | None = None,
    unite: str = "événements",
):
    """Met à jour seulement la boucle interne tout en conservant l'étape courante."""
    with _LOCK:
        fait = int(_ETAT.get("fait") or 0)
        total = int(_ETAT.get("total") or 0)
        job = _ETAT.get("job")
        ensuite = _ETAT.get("ensuite")
    publier(
        fait,
        total,
        job=job,
        ensuite=ensuite,
        detail=detail,
        traite=0 if traite is None else traite,
        traite_total=0 if traite_total is None else traite_total,
        unite=unite,
    )


def sous_phase(
    sous_fait: int,
    sous_total: int,
    *,
    job: str | None = None,
    ensuite: str | None = None,
    detail: str | None = None,
    traite: int | None = None,
    traite_total: int | None = None,
    unite: str = "éléments",
) -> None:
    """Met à jour une sous-phase sans écraser la progression globale du cycle."""
    with _LOCK:
        fait = int(_ETAT.get("fait") or 0)
        total = int(_ETAT.get("total") or 0)
        job_actuel = _ETAT.get("job")
        ensuite_actuel = _ETAT.get("ensuite")
    publier(
        fait,
        total,
        job=job if job is not None else job_actuel,
        ensuite=ensuite if ensuite is not None else ensuite_actuel,
        detail=detail,
        sous_fait=sous_fait,
        sous_total=sous_total,
        traite=0 if traite is None else traite,
        traite_total=0 if traite_total is None else traite_total,
        unite=unite,
    )


def heartbeat(*, detail: str | None = None) -> None:
    """Prouve chaque seconde que le worker vit, sans inventer de compteur."""
    with _LOCK:
        now = time.time()
        _ETAT["heartbeat_maj"] = now
        _ETAT["heartbeat_sequence"] = int(_ETAT.get("heartbeat_sequence") or 0) + 1
        if detail:
            _ETAT["detail"] = detail


def _projection_locked(e: dict, now: float) -> dict:
    """ETA toujours visible, recalculée à la lecture et fondée sur le débit observé."""
    done, total, mode = _compteur(e)
    scope = _scope(e)
    samples = [s for s in _ECHANTILLONS if s["scope"] == scope and s["total"] == total]
    if samples:
        cutoff = now - 120.0
        recents = [s for s in samples if s["ts"] >= cutoff]
        if len(recents) >= 2:
            samples = recents
    debit = None
    source = "projection_initiale"
    confiance = 5
    if len(samples) >= 2:
        premier = next((s for s in samples if s["done"] < samples[-1]["done"]), None)
        if premier is not None:
            # Le point final est "maintenant" : si le compteur stagne, l'ETA se
            # dégrade chaque seconde au lieu de rester mensongèrement figée.
            delta = samples[-1]["done"] - premier["done"]
            duree = max(0.001, now - premier["ts"])
            if delta > 0:
                debit = delta / duree
                source = "debit_glissant"
                confiance = min(95, 35 + int(min(60.0, duree)))
    if debit is None:
        historique = _DEBITS_HISTORIQUES.get(scope)
        if historique:
            debit = statistics.median(historique)
            source = "historique_phase"
            confiance = 45
    if debit is None:
        elapsed = max(0.001, now - float(e.get("sous_tache_t0") or now))
        if done > 0:
            debit = done / elapsed
            source = "moyenne_phase"
            confiance = min(40, 10 + int(min(30.0, elapsed)))
    if debit is None or debit <= 0:
        debit = _debit_initial(str(e.get("unite") or "éléments"))
    restant = max(0.0, total - done)
    eta = restant / max(debit, 1e-12) if total > 0 else 0.0
    return {
        "eta": round(eta, 1),
        "eta_source": source,
        "eta_confiance_pct": confiance,
        "eta_mode": mode,
        "debit_projection": round(debit, 3),
    }


def lire() -> dict:
    """Rend les progressions principale et interne avec fraîcheur et débits réels."""
    with _LOCK:
        e = dict(_ETAT)
        projection = _projection_locked(e, time.time())
    fait, total = e["fait"], e["total"]
    sous_fait, sous_total = e.get("sous_fait"), e.get("sous_total")
    traite, traite_total = e.get("traite"), e.get("traite_total")
    fraction_interne = (
        min(1.0, max(0.0, float(traite) / float(traite_total)))
        if traite is not None and traite_total
        else 0.0
    )
    if sous_fait is not None and sous_total:
        fraction_phase = min(
            1.0,
            max(0.0, (float(sous_fait) + fraction_interne) / float(sous_total)),
        )
    else:
        fraction_phase = fraction_interne
    avancement = float(fait) + (fraction_phase if total and fait < total else 0.0)
    pct = round(100.0 * avancement / total, 3) if total else 0.0
    maintenant = time.time()
    dt = (maintenant - e["t0"]) if e.get("t0") else 0.0
    vit = round(avancement / dt, 4) if dt > 0 and avancement > 0 else 0.0
    dt_interne = (maintenant - e["sous_tache_t0"]) if e.get("sous_tache_t0") else 0.0
    debit_interne = (
        round(float(traite) / dt_interne, 1)
        if traite is not None and traite > 0 and dt_interne > 0
        else None
    )
    age_maj = round(max(0.0, maintenant - e["compteur_maj"]), 1) if e.get("compteur_maj") else None
    age_heartbeat = (
        round(max(0.0, maintenant - e["heartbeat_maj"]), 1)
        if e.get("heartbeat_maj")
        else None
    )
    if age_heartbeat is None:
        statut = "DEMARRAGE"
    elif age_heartbeat > 10.0:
        statut = "SANS_HEARTBEAT"
    elif age_maj is not None and age_maj > 5.0:
        statut = "CALCUL_ACTIF"
    else:
        statut = "ACTIF"
    with _LOCK:
        journal = [dict(item) for item in _JOURNAL]
        sequence = _SEQUENCE
    return {
        "fait": fait,
        "total": total,
        "pourcentage": pct,
        "vitesse": vit,
        "eta": projection["eta"],
        "eta_source": projection["eta_source"],
        "eta_confiance_pct": projection["eta_confiance_pct"],
        "eta_mode": projection["eta_mode"],
        "debit_projection": projection["debit_projection"],
        "job": e["job"],
        "ensuite": e["ensuite"],
        "detail": e.get("detail"),
        "sous_fait": sous_fait,
        "sous_total": sous_total,
        "traite": traite,
        "traite_total": traite_total,
        "unite": e.get("unite") or "éléments",
        "debit_interne": debit_interne,
        "age_maj_s": age_maj,
        "age_heartbeat_s": age_heartbeat,
        "duree_s": round(dt, 1),
        "statut_progression": statut,
        "journal": journal,
        "sequence": sequence,
        "maj_wall": e.get("maj"),
        "heartbeat_sequence": e.get("heartbeat_sequence"),
    }


__all__ = ["reset", "publier", "pulse", "sous_phase", "heartbeat", "journaliser", "lire"]
