@echo off
rem Wrapper : EXPLORER AUTONOME sans fenetre. Herite CV_* et PYTHONPATH.
rem Ecrit son PID (explorer_autonome.pid) pour l'arret propre. PAPER / lecture seule.
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\explorer_autonome.py" --root "%CV_ROOT%." --duree-cycle-s 300 >> "%CV_ROOT%runtime\logs\explorer-autonome.log" 2>&1
