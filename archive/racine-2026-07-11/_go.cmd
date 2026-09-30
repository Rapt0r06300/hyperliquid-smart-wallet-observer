@echo off
cd /d "C:\Users\flo\Desktop\Projet invest"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*_replay_sample*' -or $_.CommandLine -like '*spawn_main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 >nul
set PYTHONPATH=src
echo ===RERUN OPTIMISE (prefilter candidats)=== > _go.txt
python _replay_sample.py >> _go.txt 2>&1
echo DONE_GO >> _go.txt
