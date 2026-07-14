@echo off
cd /d "%~dp0"
if not exist "runtime\scenarios" mkdir "runtime\scenarios"
echo stop> "runtime\scenarios\STOP_REPLAY"
echo ============================================================
echo   Signal STOP envoye au replay OUVERT.
echo   Il finit son lot en cours puis fait la validation finale
echo   (hors-echantillon + gate + plateau) et ecrit :
echo   runtime\scenarios\replay_open_report.json
echo   (peut prendre ~1-2 min. NE concerne PAS le run 4h.)
echo ============================================================
timeout /t 5 >nul
