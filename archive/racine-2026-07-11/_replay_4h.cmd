@echo off
cd /d "C:\Users\flo\Desktop\Projet invest"
set PYTHONPATH=src
title REPLAY 4H (ne pas fermer)
python _replay_4h.py > runtime\scenarios\replay_4h.log 2>&1
