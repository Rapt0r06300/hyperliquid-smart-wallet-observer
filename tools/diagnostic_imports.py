"""Diagnostic read-only: importe chaque module utilise par les lanceurs.

Aucun moteur n'est lance, aucun ordre, aucune cle, aucune signature.
"""
import importlib
import sys
import traceback

MODULES = [
    "hl_observer",
    "hl_observer.ops.verrou_lanceur",
    "hl_observer.ops.premier_lancement",
    "hl_observer.ops.preflight_lanceur",
    "hl_observer.ops.preuve_de_vie",
    "hl_observer.ops.superviseur_collecteurs",
    "hl_observer.ops.session_harvest",
    "hl_observer.ops.moniteur_sante",
    "hl_observer.ops.analyser_session",
    "hl_observer.ops.lab_alpha",
    "hl_observer.ops.portable_smoke",
    "hl_observer.runtime.replay_recorder",
]

print("interpreter:", sys.executable)
print("version:", sys.version)
failures = 0
for mod in MODULES:
    try:
        importlib.import_module(mod)
        print("OK      " + mod)
    except BaseException:
        failures += 1
        print("ECHEC   " + mod)
        traceback.print_exc()
print("total echecs:", failures)
sys.exit(1 if failures else 0)
