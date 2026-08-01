"""[LANCEUR item 10] Registre PID RÉEL du lanceur — arrêt/relance CIBLÉS, zéro orphelin.

Le bug audité : `launcher_pids.json` enregistrait `ps_pid=$PID`, le PID du powershell JETABLE qui écrit
le fichier — pas celui des vrais composants. Résultat : impossible d'arrêter proprement (on tue au
hasard ou on laisse des orphelins qui re-collectent en double).

Ici on enregistre les VRAIS PID, retrouvés par SIGNATURE de ligne de commande dans la liste des process :
  cmd (lanceur) · resource-policy · moteur/UI (`-m hl_observer ui`) · poller
  (persistent_poll_runner) · stream (stream_loop.ps1 / live-user-fills-stream) · ia-shadow (option).
Les collecteurs gardent leur registre dédié (superviseur_collecteurs) ; on les référence ici pour une
vue unique et la détection d'orphelins.

Arrêt CIBLÉ (même discipline que superviseur_collecteurs) : on ne vise QUE les PID enregistrés + leurs
enfants VÉRIFIÉS (ppid ∈ enregistrés). JAMAIS de kill global, jamais un process étranger. Injectable
(liste de process, killer) → prouvé sans Windows.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REGISTRE_RELPATH = Path("runtime") / "data" / "lanceur_pids.json"

# (clé, rôle lisible, signatures de ligne de commande). Une signature suffit pour identifier le process.
COMPOSANTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cmd", "lanceur", ("LANCER_HYPERSMART.cmd",)),
    ("resource-policy", "veille-ressources", ("resource_policy",)),
    ("ui", "moteur-ui", ("-m hl_observer ui", "hl_observer ui")),
    ("poller", "poller", ("persistent_poll_runner",)),
    ("stream", "stream-userfills", ("stream_loop.ps1", "live-user-fills-stream")),
    ("ia-shadow", "ia-shadow", ("ia_shadow_runner", "ia_shadow")),
)
_SIGNATURES_COMPOSANTS: tuple[str, ...] = tuple(s for _c, _r, sigs in COMPOSANTS for s in sigs)
_SIGNATURES_COLLECTEURS: tuple[str, ...] = ("boucle_collecteur.cmd",)


def _cmd(proc: Mapping[str, Any]) -> str:
    return str(proc.get("cmd") or proc.get("CommandLine") or "")


def _pid_par_signature(procs: Sequence[Mapping[str, Any]], signatures: Iterable[str]) -> int | None:
    sigs = tuple(signatures)
    for p in procs:
        ligne = _cmd(p)
        if any(s in ligne for s in sigs):
            pid = p.get("pid")
            if isinstance(pid, int):
                return pid
    return None


def construire_registre(procs: Sequence[Mapping[str, Any]], *, cmd_pid: int | None = None,
                        run_id: str = "", commit: str = "",
                        collecteurs: Mapping[str, int] | None = None,
                        now_ms: float | None = None) -> dict[str, Any]:
    """Construit le registre à partir des VRAIS process. `cmd_pid` (PID réel du lanceur, fourni par le
    .cmd) prime sur la détection par signature. Un composant introuvable n'est simplement pas enregistré
    (honnête : on ne fabrique pas de PID)."""
    composants: dict[str, Any] = {}
    for cle, role, sigs in COMPOSANTS:
        pid = cmd_pid if (cle == "cmd" and isinstance(cmd_pid, int)) else _pid_par_signature(procs, sigs)
        if isinstance(pid, int):
            composants[cle] = {"pid": pid, "role": role, "signature": sigs[0]}
    return {
        "run_id": run_id,
        "commit": commit,
        "ts_ms": int(now_ms if now_ms is not None else time.time() * 1000),
        "composants": composants,
        "collecteurs": {k: int(v) for k, v in dict(collecteurs or {}).items() if isinstance(v, int)},
    }


def _ecrire_atomique(chemin: Path, texte: str) -> bool:
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_suffix(chemin.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(texte)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, chemin)
        return True
    except OSError:
        return False


def ecrire_registre(root: str | Path, registre: Mapping[str, Any]) -> bool:
    return _ecrire_atomique(Path(root) / REGISTRE_RELPATH,
                            json.dumps(registre, ensure_ascii=False, indent=1))


def lire_registre(root: str | Path) -> dict[str, Any]:
    try:
        d = json.loads((Path(root) / REGISTRE_RELPATH).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pids_enregistres(registre: Mapping[str, Any]) -> set[int]:
    out: set[int] = set()
    for meta in dict(registre.get("composants") or {}).values():
        pid = meta.get("pid") if isinstance(meta, dict) else None
        if isinstance(pid, int):
            out.add(pid)
    for pid in dict(registre.get("collecteurs") or {}).values():
        if isinstance(pid, int):
            out.add(pid)
    return out


def detecter_orphelins(procs: Sequence[Mapping[str, Any]], pids_connus: set[int], *,
                       signatures: Iterable[str] = _SIGNATURES_COMPOSANTS + _SIGNATURES_COLLECTEURS,
                       ) -> list[dict[str, Any]]:
    """Process qui portent NOTRE signature mais dont le PID N'EST PAS dans le registre courant =
    orphelins d'un run précédent (crash, arrêt incomplet). À nettoyer avant un nouveau démarrage."""
    sigs = tuple(signatures)
    orphelins: list[dict[str, Any]] = []
    for p in procs:
        ligne = _cmd(p)
        pid = p.get("pid")
        if isinstance(pid, int) and pid not in pids_connus and any(s in ligne for s in sigs):
            orphelins.append({"pid": pid, "cmd": ligne[:160]})
    return orphelins


def cibles_arret(registre: Mapping[str, Any], procs: Sequence[Mapping[str, Any]]) -> set[int]:
    """PID à arrêter = enregistrés + enfants VÉRIFIÉS (ppid ∈ enregistrés). Jamais un process étranger."""
    cibles = set(pids_enregistres(registre))
    for p in procs:
        ppid = p.get("ppid")
        pid = p.get("pid")
        if isinstance(pid, int) and isinstance(ppid, int) and ppid in cibles:
            cibles.add(pid)
    return cibles


def arreter(root: str | Path, *, procs: Sequence[Mapping[str, Any]], killer: Callable[[int], bool],
            registre: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Arrêt CIBLÉ des composants du lanceur. Rend {cibles, arretes, orphelins}. Le killer n'est appelé
    QUE sur les cibles (registre + enfants vérifiés)."""
    reg = registre if registre is not None else lire_registre(root)
    cibles = cibles_arret(reg, procs)
    orphelins = detecter_orphelins(procs, set(cibles))
    arretes: list[int] = []
    for pid in sorted(cibles):
        try:
            if killer(pid):
                arretes.append(pid)
        except Exception:  # noqa: BLE001 — un killer injecté ne doit pas nous tuer
            pass
    return {"cibles": sorted(cibles), "arretes": arretes, "orphelins": orphelins}


# ── Lecture réelle des process (machine de Flo) ─────────────────────────────────────────────────────
def processus_reels() -> list[dict[str, Any]]:
    try:
        import psutil
    except Exception:  # noqa: BLE001 — psutil absent
        return []
    out: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            info = p.info
            out.append({"pid": info.get("pid"), "ppid": info.get("ppid"),
                        "name": info.get("name"), "cmd": " ".join(info.get("cmdline") or [])})
        except Exception:  # noqa: BLE001
            continue
    return out


def _tuer_reel(pid: int) -> bool:
    try:
        import psutil
        psutil.Process(int(pid)).terminate()
        return True
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(pid), 15)
            return True
        except (OSError, ValueError):
            return False


def enregistrer_depuis_disque(root: str | Path, *, cmd_pid: int | None = None, run_id: str = "",
                              commit: str = "") -> dict[str, Any]:
    """Scanne les VRAIS process + le registre collecteurs, écrit lanceur_pids.json. Rend le registre."""
    from hl_observer.ops.superviseur_collecteurs import _lire_pids
    procs = processus_reels()
    collecteurs = dict(_lire_pids(root).get("pids") or {})
    reg = construire_registre(procs, cmd_pid=cmd_pid, run_id=run_id, commit=commit,
                              collecteurs=collecteurs)
    ecrire_registre(root, reg)
    return reg


def format_registre(registre: Mapping[str, Any]) -> str:
    lignes = ["=== REGISTRE PID LANCEUR (run=%s) ===" % (registre.get("run_id") or "?")]
    for cle, meta in dict(registre.get("composants") or {}).items():
        lignes.append("  %-16s pid=%-8s %s" % (cle, meta.get("pid"), meta.get("role")))
    coll = dict(registre.get("collecteurs") or {})
    lignes.append("  collecteurs: %d enregistres" % len(coll))
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    """CLI : `python -m hl_observer.ops.registre_pids [status|arreter] [racine]`."""
    args = list(argv or [])
    cmd = args[0] if args else "status"
    racine = Path(args[1]) if len(args) > 1 else Path.cwd()
    if cmd == "arreter":
        r = arreter(racine, procs=processus_reels(), killer=_tuer_reel)
        print("[registre-pids] arret cible : %d process ; orphelins detectes : %d"
              % (len(r["arretes"]), len(r["orphelins"])), flush=True)
        return 0
    print(format_registre(lire_registre(racine)), flush=True)
    return 0


__all__ = ["REGISTRE_RELPATH", "COMPOSANTS", "construire_registre", "ecrire_registre", "lire_registre",
           "pids_enregistres", "detecter_orphelins", "cibles_arret", "arreter", "processus_reels",
           "enregistrer_depuis_disque", "format_registre", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
