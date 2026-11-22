r"""L'apprentissage parallèle du moteur, en processus AUTONOME (22/11/2026).

Pourquoi : le collecteur `userfills-live` en cours a chargé son code avant l'apprentissage parallèle ;
sans ce processus, l'horloge de la preuve (5 jours de données NEUVES) ne démarrerait qu'au prochain
redémarrage du moteur. Il lit le journal des fills et la bande de prix, et n'écrit que dans
`runtime/auto_amelioration/parallele_*`. Il n'ARME rien : l'armement du bac à sable reste réservé à la
passe du moteur. Un seul exemplaire à la fois (verrou). Paper, lecture seule du marché, aucun ordre.

    tools\python\python.exe tools\apprentissage_en_continu.py            (Ctrl+C pour arrêter)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import apprentissage_parallele as AP  # noqa: E402

VERROU = Path("runtime") / "auto_amelioration" / "apprentissage_en_continu.lock"


def _vivant(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=300.0)
    a = p.parse_args(argv)
    root = Path(a.racine)
    verrou = root / VERROU
    verrou.parent.mkdir(parents=True, exist_ok=True)
    try:
        ancien = int(verrou.read_text(encoding="utf-8").strip())
        if ancien != os.getpid() and _vivant(ancien):
            print(f"[apprentissage] deja en cours (pid {ancien}) : rien n'est lance", flush=True)
            return 3
    except (OSError, ValueError):
        pass
    verrou.write_text(str(os.getpid()), encoding="utf-8")
    try:
        while True:
            try:
                e = AP.une_passe(root, ecrire=True)
                v = e.get("verdict") or {}
                print(f"[apprentissage] {time.strftime('%H:%M:%S')} fills juges {e.get('fills_inscrits')}"
                      f" (+{e.get('fills_ce_passage')}) | en lice {v.get('en_lice')} | jours {v.get('jours_vus')}"
                      f" | {(e.get('decision') or {}).get('action')}", flush=True)
            except Exception as exc:  # noqa: BLE001 - une passe ratée n'arrête pas l'apprentissage
                print(f"[apprentissage] passe en echec : {type(exc).__name__}: {exc}"[:200], flush=True)
            time.sleep(max(30.0, a.intervalle))
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            if verrou.read_text(encoding="utf-8").strip() == str(os.getpid()):
                verrou.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
