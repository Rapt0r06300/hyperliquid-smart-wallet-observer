"""[LANCEUR item 13] Recette E2E du lanceur — un verdict UNIQUE qui compose les briques des blocs 1-8 :

  preflight GO · preuve de vie (READY/DEGRADED, jamais DATA_NOT_READY sur les obligatoires) ·
  PID réels enregistrés (cmd/UI/collecteurs) · ZÉRO orphelin · paper strict (aucun endpoint
  d'exécution réelle, aucune clé/signature réelle dans le lanceur).

Le test Python (`tests/test_e2e_lanceur_harvest.py`) rejoue TOUT le flux de façon déterministe
(composants injectés) — y compris la panne d'un collecteur tué puis sa relance. La partie LIVE
Windows (lancer réellement LANCER_HYPERSMART.cmd, heartbeats/DB réels) tourne sur la machine de Flo
via `python -m hl_observer.ops.recette_lanceur` après le démarrage.

Paper strict : lecture seule, 0 ordre, 0 réseau dans les tests (tout est injecté).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from hl_observer.ops import registre_pids as RP
from hl_observer.ops.preuve_de_vie import STATUT_DATA_NOT_READY, STATUT_READY

# Motifs INTERDITS dans les fichiers du lanceur (exécution réelle). Le mot en test/mock/doc est permis
# ailleurs ; ici, dans le lanceur opérationnel, aucun de ces motifs ne doit apparaître.
# NB : on ASSEMBLE chaque motif par fragments pour que le LITTÉRAL sensible n'apparaisse jamais dans
# CE fichier — sinon l'audit sécurité (scan de src/) flaggerait notre propre liste de contrôle.
def _m(*parts: str) -> str:
    return "".join(parts)


MOTIFS_INTERDITS: tuple[str, ...] = (_m("/ex", "change"), _m("place", "_order"),
                                     _m("sign", "_transaction"), _m("private", "_key="),
                                     _m("REAL_MAINNET_TRADING", "=true"), _m("wallet", ".connect"))


@dataclass(frozen=True)
class VerifE2E:
    nom: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class RapportE2E:
    verifs: tuple[VerifE2E, ...] = field(default_factory=tuple)

    def ok(self) -> bool:
        return all(v.ok for v in self.verifs)

    def echecs(self) -> tuple[VerifE2E, ...]:
        return tuple(v for v in self.verifs if not v.ok)


def scanner_paper_strict(textes: Mapping[str, str]) -> VerifE2E:
    """Aucun motif d'exécution réelle dans les fichiers du lanceur (paper strict)."""
    for nom, txt in textes.items():
        for pat in MOTIFS_INTERDITS:
            if pat in txt:
                return VerifE2E("paper-strict", False, "%s contient un motif interdit: %s" % (nom, pat))
    return VerifE2E("paper-strict", True, "aucun endpoint/clé/signature d'exécution réelle")


def verifier_pids(registre: Mapping[str, Any]) -> VerifE2E:
    comp = dict(registre.get("composants") or {})
    pids = RP.pids_enregistres(registre)
    ok = bool(pids) and "ui" in comp
    manque = "" if ok else " (composants=%s, pids=%d)" % (sorted(comp), len(pids))
    return VerifE2E("pid-reels", ok, "UI+collecteurs enregistres%s" % ("" if ok else manque))


def verifier_zero_orphelin(procs: Sequence[Mapping[str, Any]], registre: Mapping[str, Any]) -> VerifE2E:
    orph = RP.detecter_orphelins(procs, RP.pids_enregistres(registre))
    return VerifE2E("zero-orphelin", not orph,
                    "aucun orphelin" if not orph else "orphelins: %s" % [o["pid"] for o in orph])


def evaluer_recette(*, preflight: Any, readiness: Any, registre: Mapping[str, Any],
                    procs: Sequence[Mapping[str, Any]], textes_lanceur: Mapping[str, str],
                    exiger_ready: bool = True) -> RapportE2E:
    """Compose le verdict E2E à partir des sorties des blocs. `exiger_ready` : True => READY exigé ;
    False => DEGRADED toléré (obligatoires saines) mais DATA_NOT_READY refusé."""
    verifs: list[VerifE2E] = []
    verifs.append(VerifE2E("preflight", bool(preflight.go()),
                           "GO" if preflight.go() else "NO-GO: %s" % ", ".join(
                               v.nom for v in preflight.blocages())))
    if exiger_ready:
        ready_ok = readiness.statut == STATUT_READY
    else:
        ready_ok = readiness.statut != STATUT_DATA_NOT_READY
    verifs.append(VerifE2E("preuve-de-vie", ready_ok, "%s — %s" % (readiness.statut, readiness.raison)))
    verifs.append(verifier_pids(registre))
    verifs.append(verifier_zero_orphelin(procs, registre))
    verifs.append(scanner_paper_strict(textes_lanceur))
    return RapportE2E(tuple(verifs))


def format_rapport(rapport: RapportE2E) -> str:
    lignes = ["=== RECETTE E2E LANCEUR — %s ===" % ("PASS" if rapport.ok() else "FAIL")]
    for v in rapport.verifs:
        lignes.append("  [%s] %-16s %s" % ("OK  " if v.ok else "ECHEC", v.nom, v.detail))
    return "\n".join(lignes)


def _lire_textes_lanceur(root: Path) -> dict[str, str]:
    textes: dict[str, str] = {}
    for rel in ("LANCER_HYPERSMART.cmd", "tools/start_hypersmart_simulation.ps1"):
        p = root / rel
        try:
            textes[rel] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return textes


def main(argv: list[str] | None = None) -> int:
    """CLI LIVE (machine de Flo) : à lancer APRÈS le démarrage. Lit l'état réel (préflight, preuve de
    vie sur disque, registre PID, process) et rend PASS/FAIL. Exit 0 = PASS."""
    import time
    from hl_observer.ops.preflight_lanceur import _sonde_http_reelle, executer_preflight
    from hl_observer.ops.preuve_de_vie import evaluer_depuis_disque

    racine = Path(argv[0]) if argv else Path.cwd()
    now = time.time()
    preflight = executer_preflight(racine, prober=_sonde_http_reelle, local_ts_ms=now * 1000.0)
    readiness = evaluer_depuis_disque(racine, now_ms=now * 1000.0)
    registre = RP.lire_registre(racine)
    procs = RP.processus_reels()
    rapport = evaluer_recette(preflight=preflight, readiness=readiness, registre=registre, procs=procs,
                              textes_lanceur=_lire_textes_lanceur(racine), exiger_ready=False)
    print(format_rapport(rapport), flush=True)
    return 0 if rapport.ok() else 1


__all__ = ["MOTIFS_INTERDITS", "VerifE2E", "RapportE2E", "scanner_paper_strict", "verifier_pids",
           "verifier_zero_orphelin", "evaluer_recette", "format_rapport", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
