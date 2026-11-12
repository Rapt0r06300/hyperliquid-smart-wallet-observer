@echo off
rem Wrapper : lance le poll causal des leaders SANS fenetre, toute la sortie va
rem dans un log. Appele par LANCER_COLLECTEURS_COPY_VAULT.cmd via `start /B`.
rem Variables heritees : CV_PYTHON, CV_PY_ARGS, CV_ROOT, ALINA_POLL_SHARD_*.
rem PAPER / lecture seule. Le process ecrit son PID (poll_leaders.pid) pour que
rem le lanceur puisse l'arreter proprement au nettoyage.
rem Debit plafonne a 30 requetes/minute sur ce PC : tous les collecteurs locaux partagent UNE adresse IP
rem (1 200 unites/minute). A 55, le suivi des fills en prenait 1 100 a lui seul et tous les autres
rem collecteurs recevaient des refus (mesure du 2026-11-11). Les lanes cloud, chacune sur sa propre
rem adresse, gardent 55 (copy-vault-poll-lanes.yml).
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecter_userfills_poll.py" --root "%CV_ROOT%." --intervalle 5 --max-requests-per-min 30 --shard-count %ALINA_POLL_SHARD_COUNT% --shard-index %ALINA_POLL_SHARD_INDEX% > "%CV_ROOT%runtime\logs\poll-leaders.log" 2>&1
