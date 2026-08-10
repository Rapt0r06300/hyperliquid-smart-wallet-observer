"""Registre PID autoritaire du lanceur HyperSmart.

Les PID sont identifiés par signature *et*, en production, par appartenance au
checkout courant. Deux copies d'HyperSmart peuvent donc coexister sans qu'un
stop/restart de l'une n'enregistre ou ne tue les processus de l'autre.

Lecture seule / paper-only : ce module ne touche à aucun ordre ni secret.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REGISTRE_RELPATH = Path("runtime") / "data" / "lanceur_pids.json"

COMPOSANTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cmd", "lanceur", ("LANCER_HYPERSMART.cmd",)),
    ("resource-policy", "veille-ressources", ("resource_policy",)),
    ("moniteur", "moniteur-sante", ("hl_observer.ops.moniteur_sante", "moniteur_sante")),
    ("ui", "moteur-ui", ("-m hl_observer ui", "hl_observer ui")),
    ("poller", "poller", ("persistent_poll_runner",)),
    ("stream", "stream-userfills", ("stream_loop.ps1", "live-user-fills-stream")),
    ("ia-shadow", "ia-shadow", ("ia_shadow_runner", "ia_shadow")),
)
_SIGNATURES_COMPOSANTS: tuple[str, ...] = tuple(s for _c, _r, sigs in COMPOSANTS for s in sigs)
_SIGNATURES_COLLECTEURS: tuple[str, ...] = ("boucle_collecteur.cmd",)


def _cmd(proc: Mapping[str, Any]) -> str:
    return str(proc.get("cmd") or proc.get("CommandLine") or "")


def _normalise_path_text(value: str | Path) -> str:
    try:
        return os.path.normcase(os.path.normpath(str(Path(value).resolve())))
    except (OSError, RuntimeError, ValueError):
        return os.path.normcase(os.path.normpath(str(value)))


def _belongs_to_root(proc: Mapping[str, Any], root: str | Path | None) -> bool:
    """True si le process est prouvablement rattaché au checkout ``root``.

    ``root=None`` conserve le comportement injectable historique des tests. En
    production ``enregistrer_depuis_disque`` et ``arreter`` fournissent toujours
    la racine, donc une simple signature ``-m hl_observer`` ne suffit plus.
    """
    if root is None:
        return True
    root_text = _normalise_path_text(root).rstrip("\\/")
    command = os.path.normcase(_cmd(proc))
    executable = os.path.normcase(str(proc.get("exe") or proc.get("ExecutablePath") or ""))
    cwd = os.path.normcase(str(proc.get("cwd") or proc.get("WorkingDirectory") or ""))
    # La ligne de commande est la preuve principale sous Windows : le lanceur
    # passe des chemins absolus du checkout à ses enfants. CWD/exe sont des
    # preuves supplémentaires quand psutil les expose.
    return any(root_text and root_text in candidate for candidate in (command, cwd, executable))


def _pid_par_signature(
    procs: Sequence[Mapping[str, Any]],
    signatures: Iterable[str],
    *,
    root: str | Path | None = None,
) -> int | None:
    sigs = tuple(signatures)
    for p in procs:
        ligne = _cmd(p)
        if any(s in ligne for s in sigs) and _belongs_to_root(p, root):
            pid = p.get("pid")
            if isinstance(pid, int):
                return pid
    return None


def construire_registre(
    procs: Sequence[Mapping[str, Any]],
    *,
    cmd_pid: int | None = None,
    run_id: str = "",
    commit: str = "",
    collecteurs: Mapping[str, int] | None = None,
    now_ms: float | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Construit le registre des vrais composants.

    En production, ``root`` est obligatoire via ``enregistrer_depuis_disque`` et
    empêche qu'une autre copie HyperSmart soit sélectionnée par hasard.
    """
    composants: dict[str, Any] = {}
    for cle, role, sigs in COMPOSANTS:
        if cle == "cmd" and isinstance(cmd_pid, int):
            pid = cmd_pid
        else:
            pid = _pid_par_signature(procs, sigs, root=root)
        if isinstance(pid, int):
            composants[cle] = {"pid": pid, "role": role, "signature": sigs[0]}
    return {
        "run_id": run_id,
        "commit": commit,
        "root": _normalise_path_text(root) if root is not None else "",
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
    return _ecrire_atomique(
        Path(root) / REGISTRE_RELPATH,
        json.dumps(registre, ensure_ascii=False, indent=1),
    )


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


def detecter_orphelins(
    procs: Sequence[Mapping[str, Any]],
    pids_connus: set[int],
    *,
    signatures: Iterable[str] = _SIGNATURES_COMPOSANTS + _SIGNATURES_COLLECTEURS,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Retourne uniquement les orphelins appartenant au checkout courant."""
    sigs = tuple(signatures)
    orphelins: list[dict[str, Any]] = []
    for p in procs:
        ligne = _cmd(p)
        pid = p.get("pid")
        if (
            isinstance(pid, int)
            and pid not in pids_connus
            and any(s in ligne for s in sigs)
            and _belongs_to_root(p, root)
        ):
            orphelins.append({"pid": pid, "cmd": ligne[:160]})
    return orphelins


def cibles_arret(registre: Mapping[str, Any], procs: Sequence[Mapping[str, Any]]) -> set[int]:
    """PID à arrêter = enregistrés + descendants vérifiés."""
    cibles = set(pids_enregistres(registre))
    changed = True
    while changed:
        changed = False
        for p in procs:
            ppid = p.get("ppid")
            pid = p.get("pid")
            if isinstance(pid, int) and isinstance(ppid, int) and ppid in cibles and pid not in cibles:
                cibles.add(pid)
                changed = True
    return cibles


def arreter(
    root: str | Path,
    *,
    procs: Sequence[Mapping[str, Any]],
    killer: Callable[[int], bool],
    registre: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Arrêt ciblé du run courant ; jamais de kill global par signature seule."""
    reg = registre if registre is not None else lire_registre(root)
    cibles = cibles_arret(reg, procs)
    orphelins = detecter_orphelins(procs, set(cibles), root=root)
    arretes: list[int] = []
    for pid in sorted(cibles):
        try:
            if killer(pid):
                arretes.append(pid)
        except Exception:  # noqa: BLE001
            import logging as _lg
            _lg.getLogger(__name__).debug("echec arret pid=%s", pid, exc_info=True)
    return {"cibles": sorted(cibles), "arretes": arretes, "orphelins": orphelins}


def processus_reels() -> list[dict[str, Any]]:
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "exe", "cwd"]):
        try:
            info = p.info
            out.append(
                {
                    "pid": info.get("pid"),
                    "ppid": info.get("ppid"),
                    "name": info.get("name"),
                    "cmd": " ".join(info.get("cmdline") or []),
                    "exe": info.get("exe") or "",
                    "cwd": info.get("cwd") or "",
                }
            )
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


def enregistrer_depuis_disque(
    root: str | Path,
    *,
    cmd_pid: int | None = None,
    run_id: str = "",
    commit: str = "",
) -> dict[str, Any]:
    """Scanne les vrais process du checkout + registre collecteurs et persiste."""
    from hl_observer.ops.superviseur_collecteurs import _lire_pids

    racine = Path(root).resolve()
    procs = processus_reels()
    collecteurs = dict(_lire_pids(racine).get("pids") or {})
    reg = construire_registre(
        procs,
        cmd_pid=cmd_pid,
        run_id=run_id,
        commit=commit,
        collecteurs=collecteurs,
        root=racine,
    )
    ecrire_registre(racine, reg)
    return reg


def format_registre(registre: Mapping[str, Any]) -> str:
    lignes = ["=== REGISTRE PID LANCEUR (run=%s) ===" % (registre.get("run_id") or "?")]
    root = str(registre.get("root") or "")
    if root:
        lignes.append("  root: %s" % root)
    for cle, meta in dict(registre.get("composants") or {}).items():
        lignes.append("  %-16s pid=%-8s %s" % (cle, meta.get("pid"), meta.get("role")))
    coll = dict(registre.get("collecteurs") or {})
    lignes.append("  collecteurs: %d enregistres" % len(coll))
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    cmd = args[0] if args else "status"
    racine = Path(args[1]) if len(args) > 1 else Path.cwd()
    if cmd == "enregistrer":
        rid = args[2] if len(args) > 2 else ""
        reg = enregistrer_depuis_disque(racine, run_id=rid)
        print(format_registre(reg), flush=True)
        return 0
    if cmd == "arreter":
        r = arreter(racine, procs=processus_reels(), killer=_tuer_reel)
        print(
            "[registre-pids] arret cible : %d process ; orphelins detectes : %d"
            % (len(r["arretes"]), len(r["orphelins"])),
            flush=True,
        )
        return 0
    print(format_registre(lire_registre(racine)), flush=True)
    return 0


__all__ = [
    "REGISTRE_RELPATH",
    "COMPOSANTS",
    "construire_registre",
    "ecrire_registre",
    "lire_registre",
    "pids_enregistres",
    "detecter_orphelins",
    "cibles_arret",
    "arreter",
    "processus_reels",
    "enregistrer_depuis_disque",
    "format_registre",
    "main",
]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
