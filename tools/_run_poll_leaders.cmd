@echo off
rem Wrapper : lance le poll causal des leaders SANS fenetre, toute la sortie va
rem dans un log. Appele par LANCER_COLLECTEURS_COPY_VAULT.cmd via `start /B`.
rem Variables heritees : CV_PYTHON, CV_PY_ARGS, CV_ROOT, ALINA_POLL_SHARD_*.
rem PAPER / lecture seule. Le process ecrit son PID (poll_leaders.pid) pour que
rem le lanceur puisse l'arreter proprement au nettoyage.
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecter_userfills_poll.py" --root "%CV_ROOT%." --intervalle 5 --shard-count %ALINA_POLL_SHARD_COUNT% --shard-index %ALINA_POLL_SHARD_INDEX% > "%CV_ROOT%runtime\logs\poll-leaders.log" 2>&1
