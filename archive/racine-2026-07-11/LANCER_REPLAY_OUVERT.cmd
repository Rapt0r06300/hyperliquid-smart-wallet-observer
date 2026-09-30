@echo off
cd /d "%~dp0"
set PYTHONPATH=src
title REPLAY OUVERT (tourne jusqu'a STOP_REPLAY.cmd) - ne pas fermer
echo Replay OUVERT : tourne SANS limite de temps, s'arrete quand tu lances STOP_REPLAY.cmd.
echo Progression -> SUIVRE_REPLAY_OUVERT (log: runtime\scenarios\replay_open.log)
python _replay_open.py > runtime\scenarios\replay_open.log 2>&1
