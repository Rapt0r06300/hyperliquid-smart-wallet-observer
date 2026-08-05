"""[AUD-311/351/352/373/374/375/376/377/378/379/380] Gouvernance des sources : registre unique des
BLOCKED_EXTERNAL, expiration des caches payants, interdiction basse-latence des sources lentes
(Dune/Nansen), epinglage versions/endpoints, registre licences/quotas/couts, politique cle read-only,
registre conformite, SLA par source, dashboard sante mesh, checklist onboarding, politique de retrait.
stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


class RegistreBlockedExternal:
    """Registre UNIQUE des elements BLOCKED_EXTERNAL : une seule source de verite sur ce qui est bloque
    par un besoin externe (reseau, CI, licence), avec raison + condition de levee."""

    def __init__(self) -> None:
        self._items: dict = {}

    def bloquer(self, item: str, *, raison: str, condition_levee: str) -> None:
        self._items[item] = {"item": item, "raison": raison, "condition_levee": condition_levee}

    def est_bloque(self, item: str) -> bool:
        return item in self._items

    def lister(self) -> list:
        return sorted(self._items.values(), key=lambda x: x["item"])


def cache_paye_expire(pose_le: float, ttl_s: float, maintenant: float) -> dict:
    """Un cache de donnee PAYANTE doit EXPIRER : au-dela du TTL on ne sert plus une valeur perimee
    comme si elle etait fraiche."""
    age = maintenant - pose_le
    return {"expire": age > ttl_s, "age_s": age, "ttl_s": ttl_s}


def politique_basse_latence(source: str, *,
                            sources_lentes: Sequence[str] = ("dune", "nansen", "glassnode", "defillama")) -> dict:
    """Interdit une source LENTE (Dune/Nansen/...) dans un chemin BASSE LATENCE : ces sources sont pour
    la recherche/labels, jamais pour une decision temps-reel."""
    lente = source.lower() in {s.lower() for s in sources_lentes}
    return {"source": source, "basse_latence_autorisee": not lente,
            "usage": "recherche/labels" if lente else "temps-reel"}


def pin_versions_endpoints(config: Mapping[str, Mapping]) -> dict:
    """Chaque source doit EPINGLER sa version d'API et son endpoint (pas de 'latest' silencieux)."""
    non_pinnees = [n for n, c in config.items()
                   if not c.get("version") or str(c.get("version")).lower() in ("latest", "")
                   or not c.get("endpoint")]
    return {"toutes_pinnees": len(non_pinnees) == 0, "non_pinnees": sorted(non_pinnees)}


class RegistreLicences:
    """Registre licences/quotas/couts par source : on sait ce qu'on a le droit d'utiliser, dans quelles
    limites et a quel cout."""

    def __init__(self) -> None:
        self._s: dict = {}

    def enregistrer(self, source: str, *, licence: str, quota_req_jour: int, cout_usd_mois: float) -> None:
        self._s[source] = {"source": source, "licence": licence,
                          "quota_req_jour": int(quota_req_jour), "cout_usd_mois": float(cout_usd_mois)}

    def cout_total_mois(self) -> float:
        return round(sum(s["cout_usd_mois"] for s in self._s.values()), 2)

    def quota_depasse(self, source: str, req_aujourdhui: int) -> dict:
        s = self._s.get(source)
        if not s:
            return {"connu": False}
        return {"connu": True, "depasse": req_aujourdhui > s["quota_req_jour"]}


def politique_cle_read_only(scopes: Sequence[str]) -> dict:
    """Un secret d'acces DONNEES ne porte QUE des scopes lecture : jamais order/withdraw/trade (une cle
    de collecte ne doit pas pouvoir bouger de l'argent)."""
    interdits = {"order", "trade", "withdraw", "transfer", "sign"}
    violations = sorted(s for s in scopes if s.lower() in interdits)
    return {"read_only": len(violations) == 0, "scopes_interdits": violations}


class RegistreConformite:
    """Registre conformite/CGU : chaque source porte le verdict de revue (OK/A_REVOIR/REFUSEE). Une
    source non revue ne passe pas en prod."""

    def __init__(self) -> None:
        self._c: dict = {}

    def revue(self, source: str, verdict: str) -> None:
        self._c[source] = verdict

    def utilisable(self, source: str) -> bool:
        return self._c.get(source) == "OK"


def sla_source(mesures: Mapping, *, dispo_min: float = 0.99, latence_max_ms: float = 1000.0) -> dict:
    """SLA par source : disponibilite + latence sous seuil. Hors-SLA => degradee, pas silencieusement
    acceptee."""
    dispo = float(mesures.get("disponibilite", 0.0))
    latence = float(mesures.get("latence_ms", 1e9))
    return {"respecte_sla": dispo >= dispo_min and latence <= latence_max_ms,
            "disponibilite": dispo, "latence_ms": latence}


def dashboard_sante_mesh(sources_status: Mapping[str, str]) -> dict:
    """Vue UNIQUE de la sante du Data Mesh : agrege le statut de chaque source (OK/DEGRADED/DOWN)."""
    par_etat: dict = {}
    for nom, st in sources_status.items():
        par_etat.setdefault(st, []).append(nom)
    return {"global_ok": len(par_etat.get("DOWN", [])) == 0,
            "down": sorted(par_etat.get("DOWN", [])),
            "par_etat": {k: sorted(v) for k, v in par_etat.items()}}


def checklist_onboarding(source: Mapping) -> dict:
    """Une source n'entre PAS en prod tant que la checklist (licence, endpoint, replay, lineage, sla)
    n'est pas complete."""
    requis = ("licence", "endpoint", "replay", "lineage", "sla")
    manquants = sorted(k for k in requis if not source.get(k))
    return {"complet": len(manquants) == 0, "manquants": manquants}


def politique_retrait(source: Mapping) -> dict:
    """On ne coupe pas une source sans plan : consommateurs prevenus + remplacant identifie."""
    bloquants = [k for k in ("consommateurs_prevenus", "remplacant") if not source.get(k)]
    return {"retirable": len(bloquants) == 0, "bloquants": bloquants}
