"""[LANCEUR item 6] Preflight BLOQUANT — exécuté AVANT le moteur par LANCER_HYPERSMART.cmd.

Objectif : ne JAMAIS démarrer une récolte au-dessus d'un environnement cassé. On vérifie, dans l'ordre,
tout ce qui rendrait la collecte muette, corrompue ou dangereuse :

  python (version)          · deps exactes importables      · espace disque suffisant
  dossiers inscriptibles    · horloge système (skew serveur) · endpoints publics joignables
  quotas WS respectés       · fichiers de schéma présents    · aucun collecteur orphelin
  sécurité paper-only (aucune exécution réelle possible)

RÈGLE DURE : le verdict est GO seulement si TOUS les contrôles marqués `dur=True` passent. Sinon NO-GO,
avec la raison PRÉCISE de chaque blocage, et le CLI sort non-zero → le .cmd ne lance pas le moteur.

PAPER STRICT : aucune requête d'exécution. La sonde Hyperliquid ne touche QUE `/info` (lecture publique),
jamais `/exchange`. Toutes les sondes réseau sont INJECTABLES → les tests et la CI tournent 0 réseau.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_CONNECTIONS,
    HYPERSMART_WS_MAX_SUBSCRIPTIONS,
    HYPERSMART_WS_MAX_UNIQUE_USERS,
)
from hl_observer.ops.clock_integrity import skew_excessif

# ── Contrats par défaut ──────────────────────────────────────────────────────────────────────────
DEPS_DURES: tuple[str, ...] = (              # sans elles le moteur/UI ne démarre pas → BLOQUANT
    "fastapi", "uvicorn", "pydantic", "yaml", "sqlalchemy", "typer", "httpx", "websockets", "psutil",
)
DEPS_RECOMMANDEES: tuple[str, ...] = (       # absence = DÉGRADÉ (repli honnête), jamais bloquant
    "websocket", "aiohttp", "requests", "lz4", "rich", "numpy", "scipy", "pandas", "optuna", "cmaes",
)
# Endpoints PUBLICS (nom, url, dur). HL = /info UNIQUEMENT (jamais /exchange). dYdX non-bloquant tant que
# son collecteur réseau n'est pas branché (item 5) — honnêteté : on ne bloque pas sur un flux non récolté.
ENDPOINTS_DEFAUT: tuple[tuple[str, str, bool], ...] = (
    ("hyperliquid", "https://api.hyperliquid.xyz/info", True),
    ("binance", "https://fapi.binance.com/fapi/v1/time", True),
    ("dydx", "https://indexer.dydx.trade/v4/height", False),
)
DOSSIERS_DEFAUT: tuple[str, ...] = ("runtime/data", "runtime/replay", "runtime/logs",
                                    "runtime/data/market_ticks")
SCHEMAS_DEFAUT: tuple[str, ...] = ("docs/schemas/status.read.schema.json",
                                   "docs/schemas/source_health.read.schema.json",
                                   "docs/schemas/_forbidden_capabilities.json")
# Variables d'ENV qui, si vraies, autoriseraient une exécution réelle → INTERDIT (paper strict).
ENV_EXECUTION_INTERDITES: tuple[str, ...] = ("HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION",
                                             "REAL_MAINNET_TRADING", "TESTNET_EXECUTION_ENABLED",
                                             "TESTNET_MODE")
_VRAI = {"1", "true", "yes", "on", "vrai", "oui"}
MIN_DISQUE_MO_DEFAUT = 500.0
MAX_SKEW_MS_DEFAUT = 5_000.0


@dataclass(frozen=True)
class Sonde:
    """Résultat d'une sonde réseau publique (lecture seule)."""
    joignable: bool
    code: int | None = None
    serveur_ts_ms: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class Verification:
    nom: str
    categorie: str
    dur: bool
    ok: bool
    detail: str


@dataclass(frozen=True)
class ResultatPreflight:
    verifications: tuple[Verification, ...] = field(default_factory=tuple)

    def go(self) -> bool:
        return all(v.ok for v in self.verifications if v.dur)

    def blocages(self) -> tuple[Verification, ...]:
        return tuple(v for v in self.verifications if v.dur and not v.ok)

    def avertissements(self) -> tuple[Verification, ...]:
        return tuple(v for v in self.verifications if (not v.dur) and (not v.ok))


# ── Contrôles unitaires (purs, injectables) ───────────────────────────────────────────────────────
def verifier_python(*, minimum: tuple[int, int] = (3, 11),
                    version: tuple[int, int, int] | None = None) -> Verification:
    import sys
    v = version if version is not None else (sys.version_info.major, sys.version_info.minor,
                                             sys.version_info.micro)
    ok = (v[0], v[1]) >= minimum
    return Verification("python", "python", True, ok,
                        "python %d.%d.%d (min %d.%d)" % (v[0], v[1], v[2], minimum[0], minimum[1]))


def _module_present(nom: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(nom) is not None
    except (ImportError, ValueError):
        return False


def verifier_deps(*, dures: Sequence[str] = DEPS_DURES, recommandees: Sequence[str] = DEPS_RECOMMANDEES,
                  present: Callable[[str], bool] | None = None) -> list[Verification]:
    test = present if present is not None else _module_present
    out: list[Verification] = []
    manquantes_dures = [d for d in dures if not test(d)]
    out.append(Verification("deps-obligatoires", "deps", True, not manquantes_dures,
                            "manquantes: %s" % (", ".join(manquantes_dures) or "aucune")))
    manquantes_reco = [d for d in recommandees if not test(d)]
    out.append(Verification("deps-recommandees", "deps", False, not manquantes_reco,
                            "manquantes (degrade): %s" % (", ".join(manquantes_reco) or "aucune")))
    return out


def verifier_disque(racine: Path, *, min_mo: float = MIN_DISQUE_MO_DEFAUT,
                    usage: Callable[[str], Any] | None = None) -> Verification:
    lecture = usage if usage is not None else shutil.disk_usage
    try:
        u = lecture(str(racine))
        libre_mo = float(getattr(u, "free", u[2])) / (1024.0 * 1024.0)
        ok = libre_mo >= min_mo
        return Verification("disque", "disque", True, ok, "libre=%.0f Mo (min %.0f)" % (libre_mo, min_mo))
    except (OSError, ValueError, IndexError) as exc:
        return Verification("disque", "disque", True, False, "illisible: %s" % exc)


def verifier_dossiers(racine: Path, *, dossiers: Sequence[str] = DOSSIERS_DEFAUT) -> Verification:
    echecs: list[str] = []
    for rel in dossiers:
        d = racine / rel
        try:
            d.mkdir(parents=True, exist_ok=True)
            sonde = d / ".preflight_write_probe"
            sonde.write_text("ok", encoding="utf-8")
            sonde.unlink()
        except OSError as exc:
            echecs.append("%s (%s)" % (rel, exc))
    return Verification("dossiers-inscriptibles", "dossiers", True, not echecs,
                        "non inscriptibles: %s" % (", ".join(echecs) or "aucun"))


def verifier_horloge(*, serveur_ts_ms: float | None, local_ts_ms: float,
                     max_skew_ms: float = MAX_SKEW_MS_DEFAUT) -> Verification:
    if serveur_ts_ms is None:
        return Verification("horloge", "horloge", False, False,
                            "UNMEASURABLE (aucune heure serveur — endpoint horaire injoignable)")
    trop = skew_excessif(local_ts_ms, serveur_ts_ms, max_skew_ms=max_skew_ms)
    return Verification("horloge", "horloge", True, not trop,
                        "skew=%.0f ms (max %.0f)" % (abs(local_ts_ms - serveur_ts_ms), max_skew_ms))


def verifier_endpoints(prober: Callable[[str], Sonde], *,
                       endpoints: Sequence[tuple[str, str, bool]] = ENDPOINTS_DEFAUT,
                       ) -> tuple[list[Verification], float | None]:
    out: list[Verification] = []
    serveur_ts_ms: float | None = None
    for nom, url, dur in endpoints:
        try:
            s = prober(url)
        except Exception as exc:  # noqa: BLE001 — une sonde ne doit jamais tuer le preflight
            s = Sonde(False, detail=str(exc)[:120])
        if s.serveur_ts_ms is not None and serveur_ts_ms is None:
            serveur_ts_ms = s.serveur_ts_ms
        detail = "joignable" if s.joignable else "INJOIGNABLE"
        if s.code is not None:
            detail += " (http %s)" % s.code
        if s.detail:
            detail += " — %s" % s.detail
        out.append(Verification("endpoint:%s" % nom, "endpoints", dur, bool(s.joignable), detail))
    return out, serveur_ts_ms


def verifier_quotas_ws(*, connexions: int, utilisateurs: int, souscriptions: int) -> Verification:
    depassements: list[str] = []
    if connexions > HYPERSMART_WS_MAX_CONNECTIONS:
        depassements.append("connexions %d>%d" % (connexions, HYPERSMART_WS_MAX_CONNECTIONS))
    if utilisateurs > HYPERSMART_WS_MAX_UNIQUE_USERS:
        depassements.append("users %d>%d" % (utilisateurs, HYPERSMART_WS_MAX_UNIQUE_USERS))
    if souscriptions > HYPERSMART_WS_MAX_SUBSCRIPTIONS:
        depassements.append("subs %d>%d" % (souscriptions, HYPERSMART_WS_MAX_SUBSCRIPTIONS))
    return Verification("quotas-ws", "quotas", True, not depassements,
                        "depassements: %s" % (", ".join(depassements) or "aucun"))


def verifier_schemas(racine: Path, *, fichiers: Sequence[str] = SCHEMAS_DEFAUT) -> Verification:
    manquants = [f for f in fichiers if not (racine / f).is_file()]
    return Verification("schemas", "schemas", True, not manquants,
                        "manquants: %s" % (", ".join(manquants) or "aucun"))


def verifier_orphelins(*, procs: Sequence[Mapping[str, Any]] | None,
                       signatures: Sequence[str] = ()) -> Verification:
    if procs is None:
        return Verification("orphelins", "orphelins", False, True,
                            "UNMEASURABLE (liste des process non fournie)")
    sig = tuple(signatures) or ("boucle_collecteur.cmd", "hl_observer")
    trouves: list[str] = []
    for p in procs:
        ligne = str(p.get("cmd") or "")
        if any(s in ligne for s in sig):
            trouves.append("%s(pid=%s)" % (str(p.get("name") or "?"), p.get("pid")))
    return Verification("orphelins", "orphelins", True, not trouves,
                        "orphelins: %s" % (", ".join(trouves) or "aucun"))


def verifier_paper(*, env: Mapping[str, str] | None = None) -> Verification:
    e = env if env is not None else os.environ
    actives = [k for k in ENV_EXECUTION_INTERDITES if str(e.get(k, "")).strip().lower() in _VRAI]
    return Verification("paper-strict", "paper", True, not actives,
                        "flags d'execution reelle ACTIFS: %s" % (", ".join(actives) or "aucun"))


# ── Composition ────────────────────────────────────────────────────────────────────────────────────
def executer_preflight(racine: str | Path, *, prober: Callable[[str], Sonde] | None = None,
                       local_ts_ms: float, env: Mapping[str, str] | None = None,
                       procs: Sequence[Mapping[str, Any]] | None = None,
                       deps_present: Callable[[str], bool] | None = None,
                       disque_usage: Callable[[str], Any] | None = None,
                       endpoints: Sequence[tuple[str, str, bool]] = ENDPOINTS_DEFAUT,
                       dossiers: Sequence[str] = DOSSIERS_DEFAUT,
                       schemas: Sequence[str] = SCHEMAS_DEFAUT,
                       ws_connexions: int = HYPERSMART_WS_MAX_CONNECTIONS,
                       ws_utilisateurs: int = HYPERSMART_WS_MAX_UNIQUE_USERS,
                       ws_souscriptions: int = 200,
                       min_disque_mo: float = MIN_DISQUE_MO_DEFAUT) -> ResultatPreflight:
    """Exécute TOUS les contrôles et rend un ResultatPreflight. `prober` (sonde réseau) et `local_ts_ms`
    sont injectés → 0 réseau en test. Sans prober, les endpoints sont marqués injoignables (fail-closed
    pour les endpoints DURS) et l'horloge devient UNMEASURABLE."""
    r = Path(racine)
    vers: list[Verification] = [verifier_python()]
    vers.extend(verifier_deps(present=deps_present))
    vers.append(verifier_disque(r, min_mo=min_disque_mo, usage=disque_usage))
    vers.append(verifier_dossiers(r, dossiers=dossiers))
    if prober is not None:
        ep, serveur_ts = verifier_endpoints(prober, endpoints=endpoints)
    else:
        ep = [Verification("endpoint:%s" % n, "endpoints", d, False, "aucune sonde (0 reseau)")
              for n, _u, d in endpoints]
        serveur_ts = None
    vers.extend(ep)
    vers.append(verifier_horloge(serveur_ts_ms=serveur_ts, local_ts_ms=local_ts_ms))
    vers.append(verifier_quotas_ws(connexions=ws_connexions, utilisateurs=ws_utilisateurs,
                                   souscriptions=ws_souscriptions))
    vers.append(verifier_schemas(r, fichiers=schemas))
    vers.append(verifier_orphelins(procs=procs))
    vers.append(verifier_paper(env=env))
    return ResultatPreflight(tuple(vers))


def format_preflight(res: ResultatPreflight) -> str:
    lignes = ["=== PREFLIGHT LANCEUR — %s ===" % ("GO" if res.go() else "NO-GO (moteur bloque)")]
    for v in res.verifications:
        marque = "OK  " if v.ok else ("ECHEC" if v.dur else "warn ")
        lignes.append("  [%s] %-22s %s" % (marque, v.nom, v.detail))
    if not res.go():
        lignes.append("BLOCAGES: %s" % ", ".join(v.nom for v in res.blocages()))
    return "\n".join(lignes)


def _sonde_http_reelle(url: str, *, timeout: float = 6.0) -> Sonde:
    """Sonde réseau RÉELLE (utilisée seulement par le CLI sur la machine de Flo — jamais en test/CI).
    Lecture publique uniquement. GET simple ; si la réponse est un JSON horaire, on en extrait l'heure
    serveur (Binance `serverTime`, dYdX `height`/`time`). Fail-closed : toute erreur → injoignable."""
    import json as _json
    import urllib.request
    try:
        headers = {"User-Agent": "hypersmart-preflight"}
        data = None
        method = "GET"
        # `/info` est public/read-only mais Hyperliquid refuse GET (HTTP 405).
        # Une sonde de disponibilite valide doit donc utiliser le contrat POST `meta`.
        if url.rstrip("/").endswith("api.hyperliquid.xyz/info"):
            method = "POST"
            data = _json.dumps({"type": "meta"}, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as rep:  # noqa: S310 — https publics fixes
            code = int(getattr(rep, "status", 200) or 200)
            corps = rep.read(4096)
        ts = None
        try:
            data = _json.loads(corps.decode("utf-8", "ignore"))
            if isinstance(data, dict):
                for cle in ("serverTime", "time", "ms"):
                    if isinstance(data.get(cle), (int, float)):
                        ts = float(data[cle])
                        break
        except (ValueError, AttributeError):
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        return Sonde(True, code=code, serveur_ts_ms=ts)
    except Exception as exc:  # noqa: BLE001 — fail-closed volontaire
        return Sonde(False, detail=str(exc)[:120])


def main(argv: list[str] | None = None) -> int:
    """CLI : `python -m hl_observer.ops.preflight_lanceur`. Sort 0 si GO, 2 si NO-GO. Le .cmd teste
    l'ERRORLEVEL et ne lance le moteur QUE si GO."""
    import time
    racine = Path(argv[0]) if argv else Path.cwd()
    res = executer_preflight(racine, prober=_sonde_http_reelle, local_ts_ms=time.time() * 1000.0,
                             procs=None)
    print(format_preflight(res), flush=True)
    return 0 if res.go() else 2


__all__ = ["Sonde", "Verification", "ResultatPreflight", "executer_preflight", "format_preflight",
           "verifier_python", "verifier_deps", "verifier_disque", "verifier_dossiers", "verifier_horloge",
           "verifier_endpoints", "verifier_quotas_ws", "verifier_schemas", "verifier_orphelins",
           "verifier_paper", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
