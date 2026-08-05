@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3 - AUDIT DE CABLAGE : "qui appelle ce module ?"
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   0. les fichiers que l'AST ne peut PAS lire (sinon l'audit ment)
REM   1. les tests du moteur d'audit (il doit etre sain AVANT d'accuser)
REM   2. l'audit du VRAI depot
REM   3. le registre des flags, sur la MEME source de verite
REM
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
echo.
echo   [0/3] Les fichiers illisibles (un audit bati dessus mentirait)
python tools\pourquoi_illisible.py
echo.
echo   [1/3] Les tests de l'auditeur
python -m pytest -q --tb=short -p no:cacheprovider tests\test_audit_cablage.py
echo.
echo   [2/3] L'audit du depot
python tools\auditer_cablage.py > "%~dp0rapports\t3_cablage.txt" 2>&1
type t3_cablage.txt
echo.
echo   [3/3] Le registre des flags (docs/CONFIG_FLAGS.md), meme source de verite
python tools\gen_config_flags.py
pause
