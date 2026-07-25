"""RESET PAPER VOLONTAIRE (Fix 1, 25/07) — remise à zéro EXPLICITE et RÉVERSIBLE de la simulation paper.

L'AUTOPILOT et `restart` ne remettent PLUS à zéro (equity/PnL/ledgers/positions/historique conservés). La
SEULE remise à zéro passe par ici, et EXIGE `--confirm`. AVANT toute remise à zéro, on fait une SAUVEGARDE
HORODATÉE de tout l'état paper (ledgers, positions, état UI, artefacts) dans runtime/data/_backups/reset_<ts>/.
Lecture seule côté marché : 0 ordre, 0 clé, 0 signature. Sans --confirm : refuse et ne touche à rien.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
#: fichiers d'ÉTAT paper à sauvegarder AVANT reset (ledgers, positions, état UI/PnL, artefacts).
MOTIFS_ETAT = ("*ledger*.jsonl", "*positions*.json", "*positions*.jsonl", "*equity*.json",
               "hypersmart_simulation_session.sqlite3", "hypersmart_v12_artifacts.sqlite3",
               "experimental_paper*", "carry_paper*", "raw_probe*", "cohortes*.json")


def sauvegarder(root: Path = RACINE, *, ts: str | None = None) -> Path:
    """Copie horodatée de l'état paper AVANT remise à zéro. Rend le dossier de sauvegarde. Best-effort."""
    ts = ts or time.strftime("%Y%m%d-%H%M%S")
    data = Path(root) / "runtime" / "data"
    dst = data / "_backups" / ("reset_" + ts)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for motif in MOTIFS_ETAT:
        for f in data.glob(motif):
            if f.is_file():
                try:
                    shutil.copy2(f, dst / f.name)
                    n += 1
                except OSError:
                    pass
    (dst / "MANIFEST.txt").write_text(
        "reset paper %s\n%d fichiers d'etat sauvegardes AVANT remise a zero.\n"
        "Restauration : copier ces fichiers dans runtime/data/.\n" % (ts, n), encoding="utf-8")
    return dst


def reset(root: Path = RACINE, *, starting_equity: float = 1000.0, runner=None) -> int:
    """Remise à zéro via la commande CLI existante `reset-simulation-state`. `runner` injectable (test)."""
    if runner is not None:
        return int(runner())
    env = {**os.environ, "PYTHONPATH": str(Path(root) / "src")}
    r = subprocess.run([sys.executable, "-m", "hl_observer", "reset-simulation-state",  # noqa: S603
                        "--starting-equity", str(int(starting_equity))], cwd=str(root), env=env)
    return int(r.returncode)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reset paper VOLONTAIRE (sauvegarde horodatee + remise a zero).")
    ap.add_argument("--confirm", action="store_true", help="obligatoire : confirme la remise a zero")
    ap.add_argument("--starting-equity", type=float, default=1000.0)
    a = ap.parse_args(argv)
    if not a.confirm:
        print("REFUS : reset-paper efface equity/PnL/positions. Relance avec --confirm pour confirmer.", flush=True)
        print("       (Une sauvegarde horodatee est faite AVANT toute remise a zero ; rien n'est touche ici.)", flush=True)
        return 2
    dst = sauvegarder()
    print("Sauvegarde horodatee AVANT reset : %s" % dst, flush=True)
    code = reset(starting_equity=a.starting_equity)
    print("Reset paper %s (equity=%d). Sauvegarde conservee." % (
        "OK" if code == 0 else ("ECHEC code %d" % code), int(a.starting_equity)), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
