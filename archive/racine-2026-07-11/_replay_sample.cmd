@echo off
cd /d "C:\Users\flo\Desktop\Projet invest"
set PYTHONPATH=src
if not exist runtime\scenarios\snap mkdir runtime\scenarios\snap
echo ===SNAPSHOT donnees=== > _replay_sample.txt
copy /y runtime\replay\candidates.jsonl runtime\scenarios\snap\candidates.jsonl >> _replay_sample.txt 2>&1
copy /y runtime\replay\marks.jsonl runtime\scenarios\snap\marks.jsonl >> _replay_sample.txt 2>&1
echo ===PASSE MESUREE 20k=== >> _replay_sample.txt
python _replay_sample.py >> _replay_sample.txt 2>&1
echo DONE_REPLAY_SAMPLE >> _replay_sample.txt
