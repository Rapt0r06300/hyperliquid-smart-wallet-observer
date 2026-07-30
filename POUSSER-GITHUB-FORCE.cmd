@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   HyperSmart : etat du repo (ce script ne modifie RIEN)
echo   Aucun git add, aucun commit, aucun push. Tu pousses toi-meme.
echo ============================================================
echo.
echo === git status ===
git status --short
echo.
echo === 8 derniers commits locaux ===
git log --oneline -8
echo.
echo Pour pousser quand TU veux : git push origin main
echo (ni add, ni commit, ni push --force ne sont faits ici)
echo.
pause
